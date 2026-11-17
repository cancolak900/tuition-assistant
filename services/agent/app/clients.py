"""Clients the agent tools use.

- PolicyClient: MCP client (streamable HTTP). `list_tools` gives the tool schema published by the server,
  `search` calls `search_tuition_policies`. The server is stateless, so every operation opens a short session.
- TuitionClient: REST client for the Tuition API, always through Kong and always with the user's own JWT,
  so the gateway and the API enforce the same rules as for any other caller.

Calls return a ToolOutcome instead of raising, so the LLM can read the error and explain it.
"""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

POLICY_TOOL = "search_tuition_policies"


@dataclass
class ToolOutcome:
    ok: bool
    data: Any  # result payload, or {"code", "message", ...} on error

    @classmethod
    def error(cls, code: str, message: str, **extra: Any) -> "ToolOutcome":
        return cls(False, {"code": code, "message": message, **extra})


@dataclass(frozen=True)
class RemoteTool:
    name: str
    description: str
    input_schema: dict[str, Any]


class PolicyClient:
    def __init__(self, url: str, timeout: float = 10.0, http_client_factory: Any = None) -> None:
        self.url = url
        self.timeout = timeout
        self._factory = http_client_factory or (lambda: httpx.AsyncClient(timeout=self.timeout))  # tests inject an ASGI client

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[Any]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with (
            self._factory() as http,
            streamable_http_client(self.url, http_client=http) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session

    async def list_tools(self) -> list[RemoteTool]:
        """Tools published by the MCP server. Raises if the server cannot be reached."""
        async with self._session() as session:
            result = await session.list_tools()
        return [RemoteTool(t.name, (t.description or "").strip(), dict(t.inputSchema)) for t in result.tools]

    async def search(self, query: str, top_k: int = 3) -> ToolOutcome:
        try:
            async with self._session() as session:
                res = await session.call_tool(POLICY_TOOL, {"query": query, "top_k": top_k})
        except Exception as exc:  # connection errors surface as ExceptionGroups from anyio
            logger.warning("MCP call failed: %r", exc)
            return ToolOutcome.error("POLICY_SEARCH_UNAVAILABLE", "The policy search service is not reachable.")
        if res.isError:
            text = res.content[0].text if res.content and hasattr(res.content[0], "text") else "Policy search failed."
            return ToolOutcome.error("POLICY_SEARCH_FAILED", text)
        payload = res.structuredContent
        if payload is None and res.content:
            try:
                payload = json.loads(res.content[0].text)
            except (AttributeError, ValueError):
                return ToolOutcome.error("POLICY_SEARCH_FAILED", "The policy search returned an unreadable result.")
        return ToolOutcome(True, payload)


class TuitionClient:
    def __init__(self, gateway_url: str, timeout: float = 10.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base = gateway_url.rstrip("/") + "/api/v1"
        self.timeout = timeout
        self.transport = transport  # tests inject httpx.MockTransport

    async def _request(self, method: str, path: str, token: str, request_id: str | None, **kwargs: Any) -> ToolOutcome:
        headers = {"Authorization": f"Bearer {token}"}
        if request_id:
            headers["X-Request-ID"] = request_id  # Kong keeps it, so one id links agent, gateway and API logs
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                res = await client.request(method, self.base + path, headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            logger.warning("Tuition API timed out: %r", exc)
            return ToolOutcome.error("TUITION_API_TIMEOUT", "The tuition service did not answer in time. The result is unknown.")
        except httpx.HTTPError as exc:
            logger.warning("Tuition API call failed: %r", exc)
            return ToolOutcome.error("TUITION_API_UNAVAILABLE", "The tuition service is not reachable.")
        try:
            body = res.json()
        except ValueError:
            body = None
        if res.is_success:
            return ToolOutcome(True, body)
        # Our API: {"error": {code, message, details}}; Kong plugins: {"message": "..."}.
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            out = {"code": err.get("code"), "message": err.get("message"), "httpStatus": res.status_code}
            if err.get("details") is not None:
                out["details"] = err["details"]
            return ToolOutcome(False, out)
        message = body.get("message") if isinstance(body, dict) else None
        return ToolOutcome(False, {"code": f"HTTP_{res.status_code}", "message": message or res.reason_phrase, "httpStatus": res.status_code})

    async def query_tuition(self, student_no: str, term: str | None, token: str, request_id: str | None = None) -> ToolOutcome:
        params = {"term": term} if term else None
        return await self._request("GET", f"/banking/tuition/{student_no}", token, request_id, params=params)

    async def pay_tuition(self, student_no: str, term: str, amount: str, transaction_id: str, token: str,
                          request_id: str | None = None) -> ToolOutcome:
        """POST /banking/payments. Idempotent on transactionId, so a retry can never pay twice."""
        body = {"studentNo": student_no, "term": term, "amount": amount, "transactionId": transaction_id}
        return await self._request("POST", "/banking/payments", token, request_id, json=body)
