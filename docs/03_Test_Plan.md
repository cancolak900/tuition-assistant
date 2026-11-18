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
| Agent tests | pytest + `FakeLLM` (scripted function calls); the real REST client over `httpx.MockTransport`; the real MCP client against an in-process MCP server; the Gemini adapter with the SDK call replaced | ✅ | `services/agent/tests` |
| CI | GitHub Actions; PostgreSQL 16 started by `testcontainers` on the runner; coverage report in the log | ✅ | `.github/workflows/ci.yml` |
| Gateway / E2E smoke | `scripts/smoke.sh` (curl) against the local compose stack and the AWS deployment | needs a running stack | evidence → `docs/evidence/` |
| Manual demo | Web UI scenarios A1–A6 | needs the Gemini key | screenshots and video |

How to run the tests (goes into the README): `pip install -r requirements.txt -r requirements-dev.txt && pytest -v` (add `--cov` for a coverage report). A traceability test fails if a T-xx (Tuition API) or G-xx (agent) case below has no test that names it in its docstring. Docker is required for testcontainers. Alternatively, set `TEST_DATABASE_URL` to an existing Postgres.

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

All nine run through the agent's HTTP API in `services/agent/tests/test_agent_cases.py`. The LLM is scripted; G-02 and G-05 check the exact request the REST client sends towards Kong (URL, `Authorization: Bearer <user JWT>`, payment body).

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

Run: `bash scripts/smoke.sh [base-url]` (default `http://localhost`). It needs only bash and curl and exits non-zero on failure. The rate-limit checks read `X-RateLimit-Remaining-Day` and use the extra seed students (S1004–S1030), so the script can run many times a day and never uses up the demo logins' quota.

| ID | Case | Expected |
|---|---|---|
| E-01 | Protected route without a token | 401 from Kong |
| E-02 | Protected route with a token | 200 |
| E-03 | Mobile query for one student until its daily quota is used (3 calls), then once more | that call returns 429 |
| E-04 | Mobile query for a different student after the first one is limited | 200 (separate counter) |
| E-05 | Direct backend port from outside | connection refused (only :80 open) |
| E-06 | Swagger at `/api/v1/docs` | 200 |

## 5a. Assistant scenarios A1–A6 (`scripts/scenarios.py`)

Runs the SRS scenarios against a running stack through the gateway, with the real Gemini model. Only the Python standard library is needed.

```bash
python scripts/scenarios.py                        # all six, against http://localhost (logs in as s1001)
python scripts/scenarios.py --only A1,A3           # selected scenarios
python scripts/scenarios.py --yes --amount 100     # A4 confirms without asking (it makes a simulated payment)
python scripts/scenarios.py --chat                 # free chat; a payment card asks Confirm/Cancel in the terminal
python scripts/scenarios.py --base-url http://<aws-host> --user s1002 --password 'Pass1002!'
```

For every turn it prints the tool trace (step, kind, tool, status, duration, input) and the reply, then checks the scenario: A1 policy over MCP and "September 30 … §2.1"; A2 live balance over REST; A3 both tools and a §3.x citation; A4 confirmation card first, then `SUCCESS`, the new balance and an identical answer to a repeated Confirm; A5 no data of S1002 and a 403 refusal; A6 the 4th mobile call of the day gets `429` (uses S1020 by default; `--mobile-student` picks another seed student). Without `--yes`, A4 asks before paying. The exit code is 1 if any check fails. Text checks depend on the LLM's wording, so a failed text check should be read, not just counted.

## 6. Evidence checklist (what goes into `docs/evidence/` and the README)
- [x] `pytest -v` output of a green GitHub Actions run (`docs/evidence/unit-tests-ci.log`)
- [x] 3 MCP retrieval screenshots/logs (M-03…M-05)
- [x] Agent scenarios A1 (MCP-only), A2 (REST-only), A3 (combined), each with its tool trace
- [x] A4 confirmed payment: the confirmation card, then the success message and the new balance
- [x] A5 refusal of another student's data
- [x] E-01/E-02 protected route, E-03 429 error response
- [x] Swagger UI screenshot from the deployed URL
- [ ] Demo video link
