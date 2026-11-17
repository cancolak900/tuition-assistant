"""MCP server exposing `search_tuition_policies` (FR-22, FR-23).

Built with the official MCP Python SDK (FastMCP).
- HTTP (default):  python -m app.server            -> streamable HTTP at http://<host>:8100/mcp
- stdio:           python -m app.server --stdio    -> for MCP Inspector / local clients

The BM25 index is loaded from index/policy_index.json once, at startup. It is never rebuilt per query.

Environment variables:
    MCP_INDEX_PATH     path to the prebuilt index (default: index/policy_index.json)
    MCP_HOST, MCP_PORT bind address for HTTP (default: 0.0.0.0:8100)
    MCP_ALLOWED_HOSTS  comma-separated Host headers accepted over HTTP (DNS-rebinding protection)
"""

import argparse
import logging
import os
from functools import lru_cache
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.index import PolicyIndex

logger = logging.getLogger("mcp-server")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "index" / "policy_index.json"
DEFAULT_ALLOWED_HOSTS = "mcp-server:*,localhost:*,127.0.0.1:*"
MAX_TOP_K = 10
MAX_QUERY_CHARS = 500


class PolicyMatch(BaseModel):
    section: str = Field(description='Section number to cite, e.g. "3.2"')
    heading: str = Field(description="Section heading")
    text: str = Field(description="Full text of the section")
    score: float = Field(description="BM25 relevance score (higher is better, always > 0)")


class PolicySearchResult(BaseModel):
    document: str = Field(description="Source file name")
    documentId: str = Field(description="Policy document id, e.g. UNI-TUITION-2026-01")  # noqa: N815
    matches: list[PolicyMatch] = Field(description="Best sections first; empty when nothing relevant was found")


@lru_cache
def get_index() -> PolicyIndex:
    """Load the prebuilt index once per process."""
    path = Path(os.environ.get("MCP_INDEX_PATH", DEFAULT_INDEX))
    if not path.exists():
        raise FileNotFoundError(f"Index not found at {path}. Build it first: python -m scripts.build_index")
    index = PolicyIndex.load(path)
    logger.info("Loaded policy index %s (%d sections) from %s", index.document_id, len(index.chunks), path)
    return index


def _security() -> TransportSecuritySettings:
    hosts = [h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", DEFAULT_ALLOWED_HOSTS).split(",") if h.strip()]
    origins = [f"http://{h}" for h in hosts]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins)


mcp = FastMCP(
    name="tuition-policies",
    instructions=(
        "Search the University Tuition Policies document (UNI-TUITION-2026-01) for deadlines, installments, "
        "late fees, scholarships, refunds and banking/payment rules. Results include section numbers to cite. "
        "This document contains general policy only: it never contains a student's balance or payments."
    ),
    host=os.environ.get("MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("MCP_PORT", "8100")),
    streamable_http_path="/mcp",
    stateless_http=True,  # every request is self-contained; no server-side session to lose
    json_response=True,
    transport_security=_security(),
)


@mcp.tool()
def search_tuition_policies(query: str, top_k: int = 3) -> PolicySearchResult:
    """Search the University Tuition Policies (UNI-TUITION-2026-01) for deadlines, installments,
    late fees, scholarships, refunds and banking/payment rules.

    Returns the best matching excerpts with their section number (e.g. "3.2") and heading, so the
    answer can cite "§3.2". Not a source of student balances or payment status.

    The document is in English: write the query as short English keywords, even when the student
    writes in another language (e.g. "fall installment due dates", not "güz taksit").

    Args:
        query: English keywords for the policy question, e.g. "installment eligibility".
        top_k: how many sections to return (1-10, default 3).
    """
    index = get_index()
    query = (query or "").strip()[:MAX_QUERY_CHARS]
    top_k = max(1, min(int(top_k), MAX_TOP_K))
    matches = index.search(query, top_k=top_k) if query else []
    logger.info("search_tuition_policies query=%r top_k=%d -> %s", query, top_k, [m["section"] for m in matches])
    return PolicySearchResult(document=index.document, documentId=index.document_id, matches=[PolicyMatch(**m) for m in matches])


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    """Liveness/readiness for docker compose: OK once the index is loaded."""
    index = get_index()
    return JSONResponse({"status": "ok", "documentId": index.document_id, "sections": len(index.chunks)})


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Tuition policy MCP server")
    parser.add_argument("--stdio", action="store_true", help="use the stdio transport (MCP Inspector)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    get_index()  # fail fast and load the index before serving any request
    mcp.run(transport="stdio" if args.stdio else "streamable-http")


if __name__ == "__main__":
    main()
