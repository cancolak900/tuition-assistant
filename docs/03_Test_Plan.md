# Test Plan
## AI Tuition Assistant

| Field | Value |
|---|---|
| Document ID | TP-TUITION-01 |
| Version | 1.0 |
| Date | 2026-11-17 |
| Covers | `01_SRS.md`, `02_Technical_Design.md` |

## 1. Strategy

| Level | Tool | Runs without cloud or live LLM? | Where |
|---|---|---|---|
| Unit / API tests | pytest + FastAPI `TestClient` + PostgreSQL through `testcontainers` | ✅ | `services/*/tests` |
| MCP tests | pytest; the chunker, index and tool function are called directly | ✅ | `services/mcp-server/tests` |
| Agent tests | pytest + `FakeLLM` (scripted function calls) + mocked REST/MCP clients | ✅ | `services/agent/tests` |
| CI | GitHub Actions; PostgreSQL 16 started by `testcontainers` on the runner; coverage report in the log | ✅ | `.github/workflows/ci.yml` |
| Gateway / E2E smoke | `scripts/smoke.sh` (curl) against the local compose stack and the AWS deployment | needs a running stack | evidence → `docs/evidence/` |
| Manual demo | Web UI scenarios A1–A6 | needs the Gemini key | screenshots and video |

How to run the tests (goes into the README): `pip install -r requirements.txt -r requirements-dev.txt && pytest -v` (add `--cov` for a coverage report). A traceability test fails if a T-xx case below has no test that names it in its docstring. Docker is required for testcontainers. Alternatively, set `TEST_DATABASE_URL` to an existing Postgres.

## 2. REST API test cases (each operation has ≥1 success and ≥1 failure/edge test)

| ID | Operation | Case | Expected |
|---|---|---|---|
| T-01 | Login | valid credentials | 200, JWT with role/studentNo claims |
| T-02 | Login | wrong password | 401 |
| T-03 | Query (mobile) | existing student, term given | 200, correct total/balance |
| T-04 | Query (mobile) | no term → overall + per-term breakdown | 200, sums correct |
| T-05 | Query (mobile) | unknown student | 404 |
| T-06 | Query (mobile) | malformed term `2026-WINTER` | 422 |
| T-07 | Query (banking) | student token, own number | 200 |
| T-08 | Query (banking) | student token, **other** student | 403 |
| T-09 | Query (banking) | no / expired token | 401 |
| T-10 | Query (banking) | bank token, any student | 200 |
| T-11 | Pay | partial payment | 201, remaining = balance − amount |
| T-12 | Pay | full payment | 201, remaining = 0.00 |
| T-13 | Pay | **duplicate transactionId** | 409, balance unchanged |
| T-14 | Pay | amount > balance | 422 |
| T-15 | Pay | amount ≤ 0 / > 2 decimals | 422 |
| T-16 | Pay | student pays for another student | 403 |
| T-17 | Pay | unknown term for student | 404 |
| T-18 | Add Tuition | new record | 201 CREATED |
| T-19 | Add Tuition | same student+term again | 200 UPDATED, amount changed |
| T-20 | Add Tuition | update below already-paid amount | 409 |
| T-21 | Add Tuition | non-admin token | 403 |
| T-22 | Add Tuition | invalid currency / negative amount | 422 |
| T-23 | Batch | all rows valid | successCount = n, failureCount = 0 |
| T-24 | Batch | mixed valid/invalid rows | partial success, errors list row numbers |
| T-25 | Batch | wrong CSV header / non-CSV file | 400 |
| T-26 | Unpaid | page 1 and page 2 | correct slicing, totalPages correct |
| T-27 | Unpaid | fully paid students excluded | not in items |
| T-28 | Unpaid | pageSize 0 or 101 | 422 |
| T-29 | Unpaid | non-admin | 403 |
| T-30 | Business | balance = amount − Σpayments with Decimal (0.10 + 0.20 case) | exact |

## 3. MCP test cases

| ID | Case | Expected |
|---|---|---|
| M-01 | Chunker produces one chunk per numbered section | sections 1, 2.1 … 9 present; no empty chunks |
| M-02 | Index loads from the prebuilt file without re-indexing | the build function is called 0 times per query |
| M-03 | Query "payment deadline fall" | top match §2.1 |
| M-04 | Query "installments how many" | top match §3.2 (§3.1 or §3.3 in the top 3) |
| M-05 | Query "late fee overdue" | top match §4.1 |
| M-06 | Nonsense query "zzqx" | `matches: []` |
| M-07 | Response schema | has document, documentId, section, heading, text |

M-03 to M-05 are also the **three demonstrated retrieval queries** (MCP Inspector screenshots).

## 4. Agent test cases (FakeLLM)

| ID | Case | Expected |
|---|---|---|
| G-01 | The LLM requests `search_tuition_policies` | the MCP client is called, the trace has 1 MCP step, the final text is returned |
| G-02 | The LLM requests `query_tuition` | the REST client is called with the user's JWT and the gateway base URL |
| G-03 | The LLM requests both | the trace has 2 steps in order |
| G-04 | The LLM requests `pay_tuition` | **no** REST payment call; a pendingAction is returned |
| G-05 | `/confirm` with confirm | the payment is called once with the stored transactionId |
| G-06 | `/confirm` with cancel or an expired action | no payment call |
| G-07 | `/confirm` repeated twice | the second call does not create a new payment |
| G-08 | The REST tool returns 403 | the error is passed to the LLM; nothing is leaked in the trace output |
| G-09 | The tool-round limit is exceeded | stops after 5 rounds with a safe message |

## 5. Gateway / E2E smoke (`scripts/smoke.sh`)

| ID | Case | Expected |
|---|---|---|
| E-01 | Protected route without a token | 401 from Kong |
| E-02 | Protected route with a token | 200 |
| E-03 | Mobile query ×4 for S1001 | the 4th call returns 429 |
| E-04 | Mobile query for S1002 after the S1001 limit is hit | 200 (separate counter) |
| E-05 | Direct backend port from outside | connection refused (only :80 open) |
| E-06 | Swagger at `/api/v1/docs` | 200 |

## 6. Evidence checklist (what goes into `docs/evidence/` and the README)
- [ ] `pytest -v` output and a screenshot of a green GitHub Actions run
- [ ] 3 MCP retrieval screenshots/logs (M-03…M-05)
- [ ] Agent scenarios A1 (MCP-only), A2 (REST-only), A3 (combined), each with its tool trace
- [ ] A4 confirmed payment: the confirmation card, then the success message and the new balance
- [ ] A5 refusal of another student's data
- [ ] E-01/E-02 protected route, E-03 429 error response
- [ ] Swagger UI screenshot from the deployed URL
- [ ] Demo video link
