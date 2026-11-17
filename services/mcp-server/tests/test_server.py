"""The MCP tool over a real MCP protocol session (in-memory transport), plus the HTTP health route (FR-22, FR-23)."""

import asyncio
import json

import pytest
from starlette.testclient import TestClient

from mcp.shared.memory import create_connected_server_and_client_session

TOOL = "search_tuition_policies"


def _session_call(server_module, coro_fn):
    async def run():
        async with create_connected_server_and_client_session(server_module.mcp) as session:
            return await coro_fn(session)

    return asyncio.run(run())


def _call(server_module, **arguments) -> dict:
    async def go(session):
        result = await session.call_tool(TOOL, arguments)
        assert not result.isError, result.content
        # structured result and its text rendering must agree
        assert result.structuredContent == json.loads(result.content[0].text)
        return result.structuredContent

    return _session_call(server_module, go)


def test_tool_is_listed_with_input_and_output_schema(server):
    """FR-22: a real MCP SDK server exposes search_tuition_policies(query, top_k=3)."""
    tools = _session_call(server, lambda s: s.list_tools()).tools
    assert [t.name for t in tools] == [TOOL]
    tool = tools[0]
    assert tool.inputSchema["required"] == ["query"]
    assert tool.inputSchema["properties"]["top_k"]["default"] == 3
    assert set(tool.outputSchema["properties"]) == {"document", "documentId", "matches"}
    assert "section" in json.dumps(tool.outputSchema)
    assert "balance" in tool.description.lower()  # tells the LLM this is not a source of balances


def test_response_schema(server):
    """M-07: the response has document, documentId and matches with section, heading, text (and score)."""
    body = _call(server, query="installment eligibility")
    assert (body["document"], body["documentId"]) == ("University_Tuition_Policies.md", "UNI-TUITION-2026-01")
    assert body["matches"], "expected at least one match"
    for m in body["matches"]:
        assert set(m) == {"section", "heading", "text", "score"}
        assert m["section"] and m["heading"] and m["text"] and m["score"] > 0
    assert body["matches"][0]["section"] == "3.1"


@pytest.mark.parametrize(
    ("query", "expected"),
    [("payment deadline fall", "2.1"), ("installments how many", "3.2"), ("late fee overdue", "4.1")],
    ids=["deadline", "installments", "late-fee"],
)
def test_three_retrieval_queries_through_the_protocol(server, query, expected):
    """FR-24: the three demo retrieval queries return the expected section first over MCP."""
    assert _call(server, query=query)["matches"][0]["section"] == expected


def test_nonsense_and_empty_queries_return_no_matches(server):
    assert _call(server, query="zzqx")["matches"] == []
    assert _call(server, query="   ")["matches"] == []


@pytest.mark.parametrize(("top_k", "count"), [(1, 1), (0, 1), (-5, 1), (50, 10)])
def test_top_k_is_clamped(server, top_k, count):
    """top_k is kept within 1..10 so a client cannot ask for the whole document."""
    assert len(_call(server, query="payment", top_k=top_k)["matches"]) == count


def test_missing_index_fails_loudly(server, monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_INDEX_PATH", str(tmp_path / "missing.json"))
    server.get_index.cache_clear()
    with pytest.raises(FileNotFoundError):
        server.get_index()


def test_index_is_loaded_once_per_process(server):
    """FR-21: repeated tool calls reuse the same loaded index object."""
    first = server.get_index()
    _call(server, query="refund")
    _call(server, query="scholarship")
    assert server.get_index() is first


def test_health_route_reports_loaded_index(server):
    res = TestClient(server.mcp.streamable_http_app()).get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "documentId": "UNI-TUITION-2026-01", "sections": 25}


def test_unknown_host_header_is_rejected(server):
    """DNS-rebinding protection: only the configured Host headers may reach /mcp."""
    app = server.mcp.streamable_http_app()
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
    with TestClient(app) as client:  # one client: the session manager can only start once per app
        assert client.post("/mcp", json=init, headers={**headers, "Host": "evil.example"}).status_code in (400, 403, 421)
        assert client.post("/mcp", json=init, headers={**headers, "Host": "mcp-server:8100"}).status_code == 200
