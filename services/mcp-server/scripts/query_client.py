"""Minimal MCP client: lists the server's tools and calls search_tuition_policies.

Usage:
    python -m scripts.query_client "late fee overdue" "installments how many"          # HTTP, localhost:8100
    python -m scripts.query_client --url http://mcp-server:8100/mcp "payment deadline"  # inside docker compose
    python -m scripts.query_client --stdio "refund"                                      # spawns the server over stdio
"""

import argparse
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

TOOL = "search_tuition_policies"


async def _run(session: ClientSession, queries: list[str], top_k: int) -> list[dict]:
    await session.initialize()
    tools = await session.list_tools()
    print("tools:", [t.name for t in tools.tools])
    results = []
    for q in queries:
        res = await session.call_tool(TOOL, {"query": q, "top_k": top_k})
        payload = res.structuredContent
        if isinstance(payload, dict) and "result" in payload and "matches" not in payload:
            payload = payload["result"]
        if payload is None:  # fall back to the text content
            payload = json.loads(res.content[0].text)
        results.append(payload)
        print(f"\nquery: {q!r}")
        for m in payload["matches"]:
            print(f"  §{m['section']:<4} {m['heading']:<45} score={m['score']}")
    return results


async def query(queries: list[str], url: str | None = None, stdio: bool = False, top_k: int = 3) -> list[dict]:
    if stdio:
        params = StdioServerParameters(command=sys.executable, args=["-m", "app.server", "--stdio"])
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            return await _run(session, queries, top_k)
    async with streamablehttp_client(url or "http://127.0.0.1:8100/mcp") as (read, write, _), ClientSession(read, write) as session:
        return await _run(session, queries, top_k)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("queries", nargs="+")
    parser.add_argument("--url", default=None)
    parser.add_argument("--stdio", action="store_true")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(query(args.queries, url=args.url, stdio=args.stdio, top_k=args.top_k))


if __name__ == "__main__":
    main()
