# Testing the MCP server with MCP Inspector

The MCP server exposes one tool, `search_tuition_policies(query, top_k=3)`, over streamable HTTP at `http://localhost:8100/mcp` (local compose) and over stdio.

## 1. Start the server

```bash
docker compose up -d --build mcp-server
curl http://localhost:8100/health      # {"status":"ok","documentId":"UNI-TUITION-2026-01","sections":25}
```

## 2. Open MCP Inspector (UI)

Requires Node.js 18+.

```bash
npx @modelcontextprotocol/inspector@2.13.0
```

The Inspector prints a link such as `http://127.0.0.1:6274?MCP_INSPECTOR_API_TOKEN=…` and opens it in the browser (use that exact link; the token is required). In the connection panel:

| Field | Value |
|---|---|
| Transport | `Streamable HTTP` |
| URL | `http://localhost:8100/mcp` |

Leave the other options at their defaults, click **Connect**, open **Tools**, list the tools and select `search_tuition_policies`.

## 3. The three retrieval tests (FR-24)

Enter each query, leave `top_k` at 3, click **Run Tool**:

| # | Query | Expected first match |
|---|---|---|
| 1 | `payment deadline fall` | §2.1 Fall term (deadline September 30, 2026) |
| 2 | `installments how many` | §3.2 Number and size of installments (up to three) |
| 3 | `late fee overdue` | §4.1 Late fee rule (2% one-time fee) |

Every result has the shape `{document, documentId, matches: [{section, heading, text, score}]}`.

Screenshots: `docs/evidence/mcp-inspector-1-deadline.png`, `-2-installments.png`, `-3-late-fee.png`.

## 4. Same tests from the command line

```bash
npx @modelcontextprotocol/inspector@2.13.0 --cli http://localhost:8100/mcp --transport http \
  --method tools/call --tool-name search_tuition_policies --tool-arg "query=late fee overdue"
```

The recorded output of `tools/list` and the three queries is in [`docs/evidence/mcp-retrieval-tests.log`](evidence/mcp-retrieval-tests.log).

Without Node.js, the bundled Python client does the same: `cd services/mcp-server && python -m scripts.query_client "late fee overdue"` (add `--stdio` to start the server over stdio instead of HTTP).
