"""Clients the agent tools use.

- PolicyClient: MCP client (streamable HTTP) for the policy search tool of the MCP server.
- TuitionClient: REST client for the Tuition API, always through Kong and always with the user's own JWT,
  so the gateway and the API enforce the same rules as for any other caller.

Both return a ToolOutcome instead of raising, so the LLM can read the error and explain it.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

POLICY_TOOL = "search_tuition_policies"


@dataclass
class ToolOutcome:
    ok: bool
    data: Any  # result payload, or {"code", "message"} on error

    @classmethod
    def error(cls, code: str, message: str, **extra: Any) -> "ToolOutcome":
        return cls(False, {"code": code, "message": message, **extra})


class PolicyClient:
    def __init__(self, url: str, timeout: float = 10.0) -> None:
        self.url = url
        self.timeout = timeout

    async def search(self, query: str, top_k: int = 3) -> ToolOutcome:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        try:
            async with (
                httpx.AsyncClient(timeout=self.timeout) as http,
                streamable_http_client(self.url, http_client=http) as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                res = await session.call_tool(POLICY_TOOL, {"query": query, "top_k": top_k})
        except Exception as exc:  # network errors surface as ExceptionGroups from anyio
            logger.warning("MCP call failed: %r", exc)
            return ToolOutcome.error("POLICY_SEARCH_UNAVAILABLE", "The policy search service is not reachable.")
        if res.isError:
            text = res.content[0].text if res.content else "Policy search failed."
            return ToolOutcome.error("POLICY_SEARCH_FAILED", text)
        payload = res.structuredContent
        if payload is None and res.content:
            payload = json.loads(res.content[0].text)
        return ToolOutcome(True, payload)


class TuitionClient:
    def __init__(self, gateway_url: str, timeout: float = 10.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base = gateway_url.rstrip("/") + "/api/v1"
        self.timeout = timeout
        self.transport = transport  # tests inject httpx.MockTransport

    async def _request(self, method: str, path: str, token: str, request_id: str | None, **kwargs: Any) -> ToolOutcome:
        headers = {"Authorization": f"Bearer {token}"}
        if request_id:
            headers["X-Request-ID"] = request_id
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                res = await client.request(method, self.base + path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("Tuition API call failed: %r", exc)
            return ToolOutcome.error("TUITION_API_UNAVAILABLE", "The tuition service is not reachable.")
        try:
            body = res.json()
        except ValueError:
            body = None
        if res.is_success:
            return ToolOutcome(True, body)
        # Our API: {"error": {...}}; Kong plugins: {"message": "..."}.
        err = (body or {}).get("error") if isinstance(body, dict) else None
        if err:
            return ToolOutcome(False, {"code": err.get("code"), "message": err.get("message"), "httpStatus": res.status_code})
        message = (body or {}).get("message") if isinstance(body, dict) else None
        return ToolOutcome(False, {"code": f"HTTP_{res.status_code}", "message": message or res.reason_phrase, "httpStatus": res.status_code})

    async def query_tuition(self, student_no: str, term: str | None, token: str, request_id: str | None = None) -> ToolOutcome:
        params = {"term": term} if term else None
        return await self._request("GET", f"/banking/tuition/{student_no}", token, request_id, params=params)
