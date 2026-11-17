"""PolicyClient against a real MCP server (official SDK, streamable HTTP) running in-process: no network."""

import httpx
import pytest
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from app.clients import PolicyClient
from app.tools import TOOLS, ToolExecutor
from tests.fakes import FakeTuition

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Match(BaseModel):
    section: str
    heading: str
    text: str
    score: float


class Result(BaseModel):
    document: str
    documentId: str  # noqa: N815
    matches: list[Match]


def build_server(fail: bool = False) -> FastMCP:
    server = FastMCP("tuition-policies-test", stateless_http=True, json_response=True, host="localhost")

    @server.tool()
    def search_tuition_policies(query: str, top_k: int = 3) -> Result:
        """Search the test policy document.

        Args:
            query: keywords.
        """
        if fail:
            raise ValueError("index not loaded")
        return Result(document="t.md", documentId="T-1", matches=[Match(section="2.1", heading="Fall", text=f"hit for {query} x{top_k}", score=1.0)])

    @server.tool(structured_output=False)
    def plain_text(query: str, top_k: int = 3) -> str:
        """Returns text instead of structured content (like an older server)."""
        return '{"matches": []}' if query == "json" else "not json"

    return server


@pytest.fixture
async def mcp_client(request):
    server = build_server(fail=getattr(request, "param", False))
    app = server.streamable_http_app()
    factory = lambda: httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:8100")  # noqa: E731
    async with server.session_manager.run():  # what the app lifespan would do
        yield PolicyClient("http://localhost:8100/mcp", http_client_factory=factory)


async def test_call_tool_returns_structured_result(mcp_client):
    out = await mcp_client.search("deadline", 2)
    assert out.ok
    assert out.data["matches"][0] == {"section": "2.1", "heading": "Fall", "text": "hit for deadline x2", "score": 1.0}


@pytest.mark.parametrize(("kind", "ok"), [("json", True), ("text", False)])
async def test_text_only_results_are_parsed_or_rejected(mcp_client, monkeypatch, kind, ok):
    import app.clients as clients

    monkeypatch.setattr(clients, "POLICY_TOOL", "plain_text")
    out = await mcp_client.search(kind)
    assert out.ok is ok and (out.data == {"matches": []} if ok else out.data["code"] == "POLICY_SEARCH_FAILED")


async def test_list_tools_returns_the_published_schema(mcp_client):
    tool = next(t for t in await mcp_client.list_tools() if t.name == "search_tuition_policies")
    assert tool.name == "search_tuition_policies"
    assert tool.input_schema["required"] == ["query"] and "top_k" in tool.input_schema["properties"]
    assert tool.description.startswith("Search the test policy document.")


@pytest.mark.parametrize("mcp_client", [True], indirect=True)
async def test_tool_error_is_reported(mcp_client):
    out = await mcp_client.search("x")
    assert (out.ok, out.data["code"]) == (False, "POLICY_SEARCH_FAILED")
    assert "index not loaded" in out.data["message"]


async def test_executor_uses_the_server_schema(mcp_client):
    executor = ToolExecutor(mcp_client, FakeTuition())
    specs = await executor.specs()
    assert [s.name for s in specs] == [t.name for t in TOOLS]
    assert specs[0].description.startswith("Search the test policy document.")  # from the server, not the built-in copy
    assert specs[0].parameters["properties"]["top_k"]["default"] == 3


async def test_unreachable_server_falls_back_to_the_built_in_schema():
    client = PolicyClient("http://127.0.0.1:9/mcp", timeout=2)
    executor = ToolExecutor(client, FakeTuition())
    assert (await executor.specs())[0] is TOOLS[0]
    assert executor._retry_at > 0  # retried later, not on every message
    out = await client.search("deadline")
    assert (out.ok, out.data["code"]) == (False, "POLICY_SEARCH_UNAVAILABLE")
