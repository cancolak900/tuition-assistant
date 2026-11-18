# AI Tuition Assistant

[![CI](https://github.com/cancolak900/tuition-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/cancolak900/tuition-assistant/actions/workflows/ci.yml)

A conversational assistant for university students. It answers questions about tuition deadlines, installments, late fees and payment rules, shows the student's live balance, and makes simulated payments after explicit confirmation.

An LLM (Google Gemini, real function calling) picks the tools. The agent runs each call and returns the results to the model, so every answer is grounded:
- **Policy questions** go to an **MCP server** with a BM25 index of the policy document.
- **Live data and payments** go to a **REST API through a Kong API gateway**. The data lives in PostgreSQL on Amazon RDS.

| | |
|---|---|
| **Live demo** | **https://tuition.cancolak.dev** (AWS EC2 + RDS, HTTPS) |
| **API gateway base URL** | `https://tuition.cancolak.dev/api/v1` (fallback without TLS: `http://18.153.247.247/api/v1`) |
| **Swagger UI** | https://tuition.cancolak.dev/api/v1/docs · [docs/openapi.json](docs/openapi.json) |
| **Demo video** | *added after recording* |

---

## Contents
1. [What it does](#1-what-it-does)
2. [Architecture](#2-architecture)
3. [Demo accounts and test data](#3-demo-accounts-and-test-data)
4. [API gateway: URL, routes, errors](#4-api-gateway-url-routes-errors)
5. [REST API](#5-rest-api)
6. [Authentication and authorization](#6-authentication-and-authorization)
7. [AI agent and tool calling](#7-ai-agent-and-tool-calling)
8. [MCP server: tool schema and indexing](#8-mcp-server-tool-schema-and-indexing)
9. [Database](#9-database)
10. [Run it locally](#10-run-it-locally)
11. [Tests](#11-tests)
12. [Reproducing the results](#12-reproducing-the-results)
13. [Evidence](#13-evidence)
14. [Cloud deployment](#14-cloud-deployment)
15. [Costs](#15-costs)
16. [Assumptions](#16-assumptions)
17. [Design decisions](#17-design-decisions)
18. [Repository layout and documents](#18-repository-layout-and-documents)

---

## 1. What it does

| The student asks | Tools the LLM chooses | Result |
|---|---|---|
| "When is the Fall payment deadline?" | `search_tuition_policies` (MCP) | September 30, 2026, citing §2.1 |
| "What is my balance?" | `query_tuition` (REST via Kong) | Live balance per term |
| "Can I pay my balance in installments?" | `query_tuition` + `search_tuition_policies` | Checks the balance against the §3.1 rules |
| "Pay $500 of my Fall tuition" | `query_tuition`, then `pay_tuition` | A **confirmation card**. Nothing is paid until the student presses **Confirm**. |
| "What is the balance of S1002?" | `query_tuition` → 403 | Refused. A student only sees their own records, whatever the prompt says. |

The chat answers in the student's language (English or Turkish). Under every answer a **tool trace** lists each step: tool, input, result summary and duration. Each line opens the full JSON result.

Besides the chat, the web app has an **admin screen**:
- add or update tuition
- upload tuition in bulk from a CSV
- list unpaid tuition, paged

The UI works on desktop and phone.

## 2. Architecture

```mermaid
flowchart LR
    U[Student / admin<br/>browser] -->|HTTPS| C[Caddy<br/>TLS :443]
    C --> K[Kong API Gateway<br/>JWT · rate limits · request id]
    K -->|/| W[Web UI<br/>React + nginx]
    K -->|/api/v1/agent| AG[AI Agent<br/>FastAPI]
    K -->|/api/v1/auth · banking · mobile · admin| API[Tuition API<br/>FastAPI]
    AG <-->|function calling| LLM[(Google Gemini)]
    AG -->|REST with the user's JWT| K
    AG -->|MCP client · streamable HTTP| MCP[MCP Server<br/>search_tuition_policies<br/>BM25 index]
    API --> DB[(PostgreSQL 16<br/>Amazon RDS)]
```

- **All REST traffic goes through Kong**, including the agent's own calls to the Tuition API. The agent forwards the student's JWT, so the API applies the same authorization to the agent as to any client.
- **The MCP path is separate from the gateway path.** The agent is an MCP client and talks to the MCP server inside the private Docker network.
- **The LLM never calls a backend.** It only returns function calls. The agent validates and runs them, and payments additionally need the student's confirmation.
- **Only Caddy is exposed** (80/443). Kong, the services and the MCP server have no public ports, and the database is not publicly accessible. The smoke test checks this.

| Component | Stack | Code |
|---|---|---|
| Tuition API | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PyJWT, bcrypt | [services/tuition-api](services/tuition-api) |
| MCP server | Official MCP Python SDK (FastMCP), rank-bm25 | [services/mcp-server](services/mcp-server) |
| AI agent | FastAPI, google-genai (Gemini function calling), MCP client | [services/agent](services/agent) |
| API gateway | Kong Gateway OSS 3.x, DB-less declarative config | [gateway](gateway) |
| Web UI | React 19, Vite, TypeScript, Tailwind CSS 4 | [web](web) |
| Database | PostgreSQL 16 (Docker locally, Amazon RDS in the cloud) | [models](services/tuition-api/app/models.py) |
| TLS edge (AWS only) | Caddy 2, Let's Encrypt | [gateway/caddy](gateway/caddy/Caddyfile) |

The full design (contracts, data model, sequence diagrams, ADRs) is in [docs/02_Technical_Design.md](docs/02_Technical_Design.md).

## 3. Demo accounts and test data

| Username | Password | Role | Data |
|---|---|---|---|
| `s1001` | `Pass1001!` | student S1001 | 2026-FALL $3,000 unpaid, 2027-SPRING $3,000 unpaid |
| `s1002` | `Pass1002!` | student S1002 | 2026-FALL $2,500, fully paid (balance 0) |
| `s1003` | `Pass1003!` | student S1003 | 2026-FALL $250 (below the $300 installment threshold of §3.1) |
| `bank` | `Bank123!` | bank | may query and pay for any student |
| `admin` | `Admin123!` | admin | add tuition, batch upload, unpaid list |

- Students S1004–S1030 have tuition but no login, so the unpaid list spans several pages.
- [seed/sample_batch.csv](services/tuition-api/seed/sample_batch.csv) mixes valid rows with deliberately invalid ones for the batch upload.
- The seed is idempotent: `python -m seed.seed` never duplicates rows.
- The demo data on AWS can be restored with `bash scripts/deploy.sh reset-data`.

## 4. API gateway: URL, routes, errors

**Gateway URL:** `https://tuition.cancolak.dev`. All public routes are versioned under `/api/v1`. Config: [gateway/kong.yml.template](gateway/kong.yml.template).

| Public route (Kong) | Upstream | Gateway policy |
|---|---|---|
| `POST /api/v1/auth/login` | tuition-api | rate limit 20/min per IP (brute force) |
| `GET /api/v1/mobile/tuition/{studentNo}` | tuition-api | **no auth**, **3 calls per student per day** (see below) |
| `GET /api/v1/banking/tuition/{studentNo}` | tuition-api | **JWT** |
| `POST /api/v1/banking/payments` | tuition-api | **JWT** |
| `GET /api/v1/auth/me` | tuition-api | **JWT** |
| `POST /api/v1/admin/tuition` | tuition-api | **JWT** (+ role `admin` in the API) |
| `POST /api/v1/admin/tuition/batch` | tuition-api | **JWT** (+ role `admin`) |
| `GET /api/v1/admin/tuition/unpaid` | tuition-api | **JWT** (+ role `admin`) |
| `POST /api/v1/agent/chat`, `POST /api/v1/agent/confirm` | agent | **JWT**, 20/min per client |
| `GET /api/v1/docs`, `/api/v1/openapi.json`, `/api/v1/health` | tuition-api | public |
| `/` (everything else) | web | public static UI |

Every response carries an `X-Request-ID` header (Kong correlation-id). The agent forwards it on its REST calls, so one id links the Kong, agent and API logs.

**Mobile limit keyed by student identity, not by IP.**
- Kong captures `{studentNo}` from the path into a header and runs `rate-limiting` with `day: 3, limit_by: header`.
- A client-supplied `X-RateLimit-Student` header is overwritten, so it cannot be used to get around the limit.
- The fourth call of the day for the same student gets `429`, even from a different IP. Another student has a separate counter. The day is the calendar day in UTC.

**Error responses** (captured from the running system):

```http
GET /api/v1/banking/tuition/S1001            (no token: rejected by Kong)
HTTP/1.1 401 Unauthorized
{"message":"Unauthorized"}

GET /api/v1/banking/tuition/S1002            (token of s1001: rejected by the API)
HTTP/1.1 403 Forbidden
{"error":{"code":"FORBIDDEN_OTHER_STUDENT","message":"You can only access your own tuition records.","details":null}}

POST /api/v1/banking/payments  {"studentNo":"S1001","term":"2026-FALL","amount":"999999.00","transactionId":"DOC-1"}
HTTP/1.1 422 Unprocessable Entity
{"error":{"code":"AMOUNT_EXCEEDS_BALANCE","message":"The amount is greater than the remaining balance.","details":{"amount":"999999.00","balance":"0.00","currency":"USD"}}}

GET /api/v1/mobile/tuition/S1029             (4th call today)
HTTP/1.1 429 Too Many Requests
{"message":"Daily limit reached: at most 3 tuition queries per student per day.","request_id":"e0f2ff6abbb12d7c6eda3754c9ca336c"}
```

The API's errors always have the shape `{"error":{"code","message","details"}}`. The codes are listed in [the design document §5](docs/02_Technical_Design.md#5-rest-api-contract-v1).

## 5. REST API

| Client | Operation | Endpoint | Auth | Paging |
|---|---|---|---|---|
| Mobile app | Query Tuition | `GET /api/v1/mobile/tuition/{studentNo}?term=` | No | No |
| Banking app | Query Tuition | `GET /api/v1/banking/tuition/{studentNo}?term=` | Yes | No |
| Banking app | Pay Tuition | `POST /api/v1/banking/payments` | Yes | No |
| Admin web | Add Tuition | `POST /api/v1/admin/tuition` | Yes | No |
| Admin web | Add Tuition – Batch | `POST /api/v1/admin/tuition/batch` (CSV `studentNo,term,amount,currency`) | Yes | No |
| Admin web | Unpaid Tuition Status | `GET /api/v1/admin/tuition/unpaid?term=&page=&pageSize=` | Yes | **Yes** |

**Query Tuition**
- With `term`, it returns that term's tuition total, paid amount and balance.
- Without `term`, it returns the overall total and balance plus a per-term breakdown.

**Pay Tuition** records a simulated full or partial payment and answers with status, paid amount and remaining balance. It rejects:
- an amount above the remaining balance, including any payment when nothing is owed (`422 AMOUNT_EXCEEDS_BALANCE`)
- a reused `transactionId` (`409 DUPLICATE_TRANSACTION`, nothing is recorded twice)

The tuition row is locked during a payment (`SELECT … FOR UPDATE`), so concurrent payments cannot overdraw it. No real money or card data is involved.

**Add Tuition**
- If the record exists for the student and term, the call updates it (`200 UPDATED`, old → new amount). Otherwise it creates one (`201 CREATED`).
- The amount may not drop below what has already been paid (`409 AMOUNT_BELOW_PAID`).
- The currency cannot change once payments exist (`409 CURRENCY_CHANGE_NOT_ALLOWED`).
- The student must exist (`404 STUDENT_NOT_FOUND`); students are never created implicitly.

**Batch upload** processes every row on its own and reports processed / succeeded / failed counts, plus the row number and reason for each failure.

Contract details: [docs/02_Technical_Design.md §5](docs/02_Technical_Design.md#5-rest-api-contract-v1), [Swagger UI](https://tuition.cancolak.dev/api/v1/docs), [openapi.json](docs/openapi.json).

## 6. Authentication and authorization

- **JWT (HS256)** is issued by `POST /api/v1/auth/login`, with a 60-minute expiry. The token is verified twice: by Kong's `jwt` plugin and by the API.
- **Roles:**
  - `student` sees and pays only their own tuition; the student number comes from the token, not from the request.
  - `bank` may query and pay for any student.
  - `admin` manages tuition.
- **The agent cannot be talked into another student's data.** It calls the API with the student's own JWT, so asking about S1002 while signed in as s1001 ends in a `403` from the API. The model then gets a one-sentence refusal that reveals nothing about S1002.
- **Payments need explicit confirmation, enforced in code, not in the prompt:**
  1. `pay_tuition` only creates a pending action.
  2. The UI shows a card with the amount and the balance after payment. It expires after 5 minutes.
  3. Only `POST /api/v1/agent/confirm` with the student's decision calls the Pay Tuition API.
- Passwords are stored as bcrypt hashes. The web app keeps the token in `sessionStorage`, never in `localStorage` or cookies.

## 7. AI agent and tool calling

- **LLM:**
  - Google Gemini via `google-genai`, with **manual function calling**: the model returns function calls, and the agent executes them.
  - Up to 5 tool rounds per turn, temperature 0.2.
  - Primary model `gemini-flash-latest`. On overload or quota errors it falls back to `gemini-flash-lite-latest`, then `gemini-2.5-flash-lite`.
- **Tools:**

  | Tool | Kind | What the agent does |
  |---|---|---|
  | `search_tuition_policies(query, top_k)` | MCP | Calls the MCP server and returns excerpts with section numbers. The schema is read from the server (`tools/list`). |
  | `query_tuition(studentNo, term?)` | REST | `GET /api/v1/banking/tuition/{studentNo}` **through Kong** with the student's JWT |
  | `pay_tuition(term, amount)` | local → REST | Checks the balance, then creates a **pending action**; `/confirm` calls `POST /api/v1/banking/payments` through Kong. The transaction id is generated by the agent, not the LLM. |

- **System prompt** ([prompts.py](services/agent/app/prompts.py)):
  - Never guess: use the tools.
  - Cite `§section` for policy answers.
  - For installment questions, check the live balance as well as the policy.
  - Never claim a payment succeeded without an API success.
  - Show one payment card at a time.
  - These rules cannot be overridden or revealed by the user.
- **Tool trace:** every chat and confirm response returns `trace[]` with `{step, kind, tool, input, status, output, durationMs}`. The web UI shows it under each answer, and the agent also logs it as one JSON line per turn. An example is in [docs/evidence/agent-trace.log](docs/evidence/agent-trace.log).
- **Resilience:**
  - Retries on 5xx from the model.
  - 25 s per LLM call and 80 s per turn.
  - Payment results after `/confirm` are fixed texts (English or Turkish), never LLM output.
  - A payment whose outcome is unknown (timeout) keeps its card, and retrying uses the same transaction id, so a duplicate charge is impossible.

## 8. MCP server: tool schema and indexing

- **Tool:** `search_tuition_policies(query: str, top_k: int = 3)`. It returns `{document, documentId, matches:[{section, heading, text, score}]}`.
  - The full schema the server advertises (input and output JSON Schema) plus an example call: [docs/mcp-tool-schema.json](docs/mcp-tool-schema.json).
  - Transport: streamable HTTP (`/mcp`, internal only) and stdio (for MCP Inspector).
- **Source document:** [University_Tuition_Policies.md](services/mcp-server/data/University_Tuition_Policies.md).
- **Chunking:** one chunk per numbered section (`2.1`, `3.2`, …). A top-level section without subsections becomes one chunk. That gives 25 chunks, each keeping its section number and heading.
- **Indexing:**
  - Runs at **Docker build time** ([build_index.py](services/mcp-server/scripts/build_index.py)): lowercasing, punctuation and English stopword removal, a light stemmer, and headings weighted 2×. The result is written to `index/policy_index.json`.
  - At startup the server loads the index into BM25 **once**. Nothing is re-indexed per question.
  - Full-text search, so no embeddings and no cost.
- **Three retrieval tests** (MCP Inspector screenshots and a log):

  | Query | First match |
  |---|---|
  | `payment deadline fall` | §2.1 Fall term (September 30, 2026) · [screenshot](docs/evidence/mcp-inspector-1-deadline.png) |
  | `installments how many` | §3.2 Number and size of installments · [screenshot](docs/evidence/mcp-inspector-2-installments.png) |
  | `late fee overdue` | §4.1 Late fee rule · [screenshot](docs/evidence/mcp-inspector-3-late-fee.png) |

  The same tests as a log: [mcp-retrieval-tests.log](docs/evidence/mcp-retrieval-tests.log). How to repeat them with MCP Inspector: [docs/mcp-inspector.md](docs/mcp-inspector.md).

## 9. Database

PostgreSQL 16 (Amazon RDS `db.t4g.micro` in the cloud). The schema is managed by Alembic migrations.

![ER diagram](docs/er-diagram.png)

- Unique `(student_no, term)` on tuitions.
- Check constraints: amounts > 0, term format, ISO-4217 currency, payment channel.
- Unique `transaction_id` on payments.
- The balance is computed (`amount − SUM(payments)`), never stored, so it cannot drift.

## 10. Run it locally

**Requirements:** Docker with Compose v2, and a free Gemini API key from Google AI Studio (needed only for the chat).

```bash
git clone https://github.com/cancolak900/tuition-assistant.git && cd tuition-assistant
cp .env.example .env                 # set POSTGRES_PASSWORD, DATABASE_URL, JWT_SECRET, GEMINI_API_KEY
docker compose up -d --build
docker compose run --rm tuition-api alembic upgrade head
docker compose run --rm tuition-api python -m seed.seed
```

Then open:
- http://localhost: web UI. Sign in with a [demo account](#3-demo-accounts-and-test-data).
- http://localhost/api/v1/docs: Swagger UI through Kong.

| Note | Detail |
|---|---|
| `JWT_SECRET` | Use URL-safe characters (`A-Z a-z 0-9 - _`). |
| Port 80 in use | Set `GATEWAY_PORT` in `.env`. |
| Local-only ports | Postgres `127.0.0.1:5432` and the MCP server `127.0.0.1:8100` (for MCP Inspector) are published only on localhost. |
| Without a Gemini key | Everything except the chat works. Unit tests never need a key. |
| Reset local data | `docker compose down -v`, then repeat the last three commands. |

## 11. Tests

Unit tests cover **every REST API operation** with success and failure/edge cases (business rules, validation, responses), plus the MCP server, the agent and the web UI. They run **without the cloud and without a live LLM**:
- the agent tests use a scripted fake LLM
- the API tests start a throwaway PostgreSQL with testcontainers

| Suite | Tests | Coverage | Run |
|---|---|---|---|
| Tuition API | 118 | 99% | `cd services/tuition-api && pip install -r requirements.txt -r requirements-dev.txt && pytest -v --cov` (needs Docker for testcontainers) |
| MCP server | 30 | 95% | `cd services/mcp-server && pip install -r requirements.txt -r requirements-dev.txt && pytest -v --cov` |
| AI agent | 130 | 99% | `cd services/agent && pip install -r requirements.txt -r requirements-dev.txt && pytest -v --cov` |
| Web UI | 84 | – | `cd web && npm ci && npm test` |

- **CI:** [GitHub Actions](https://github.com/cancolak900/tuition-assistant/actions/workflows/ci.yml) runs all four suites on every push. Full output of a green run: [docs/evidence/unit-tests-ci.log](docs/evidence/unit-tests-ci.log).
- **Test plan:** [docs/03_Test_Plan.md](docs/03_Test_Plan.md). §2 maps every operation to its success and failure tests, and the `test_plan_traceability.py` files check that each planned case exists.

**End-to-end checks** against a running stack, local or cloud:

```bash
bash scripts/smoke.sh https://tuition.cancolak.dev        # gateway: health, login, JWT, 401/403, mobile 429, closed ports, Swagger, web
python scripts/scenarios.py --base-url https://tuition.cancolak.dev --yes   # agent scenarios A1–A6 with the real LLM
```

`smoke.sh` needs only bash and curl. `scenarios.py` uses only the Python standard library. Without `--yes`, it asks before the confirmed payment in A4.

## 12. Reproducing the results

1. **Unit tests:** run the commands in [§11](#11-tests), or open the latest CI run.
2. **Gateway:** run `bash scripts/smoke.sh https://tuition.cancolak.dev`. All checks should pass: 401 without a token, 200 with one, 403 for another student, 429 on the 4th mobile call, backend ports closed.
3. **Agent scenarios:** run `python scripts/scenarios.py --base-url https://tuition.cancolak.dev --yes`. It covers:
   - A1 MCP-only
   - A2 REST-only
   - A3 combined
   - A4 payment with confirmation
   - A5 refusal of another student's data
   - A6 mobile 429
4. **By hand in the web UI** (https://tuition.cancolak.dev):
   1. Sign in as `s1001`.
   2. Ask "When is the Fall payment deadline?", "What is my balance?" and "Can I pay my Fall balance in installments?".
   3. Open the tool trace under each answer.
   4. Ask "Pay $500 of my Fall tuition", check the card, then press **Confirm**.
   5. Sign in as `admin` to see the unpaid list and to upload [sample_batch.csv](services/tuition-api/seed/sample_batch.csv).
5. **MCP retrieval:** follow [docs/mcp-inspector.md](docs/mcp-inspector.md).

The scenarios change the demo data (A4 pays $500 for S1001). Run `bash scripts/deploy.sh reset-data` on the server, or reseed locally, to start fresh.

## 13. Evidence

All files are in [docs/evidence](docs/evidence).

<p>
  <img src="docs/evidence/live-a3-combined.jpg" alt="Combined MCP + REST answer with tool trace" width="49%">
  <img src="docs/evidence/live-a4-payment-confirmed.jpg" alt="Confirmed simulated payment" width="49%">
</p>

| What | File |
|---|---|
| **Live system screenshots** (https://tuition.cancolak.dev, tool trace open) | A1 MCP-only: [live-a1-mcp-only.jpg](docs/evidence/live-a1-mcp-only.jpg) · A2 API-only: [live-a2-rest-only.jpg](docs/evidence/live-a2-rest-only.jpg) · A3 combined: [live-a3-combined.jpg](docs/evidence/live-a3-combined.jpg) · A4 confirmation card: [live-a4-confirmation-card.jpg](docs/evidence/live-a4-confirmation-card.jpg) → confirmed payment: [live-a4-payment-confirmed.jpg](docs/evidence/live-a4-payment-confirmed.jpg) · A5 refusal: [live-a5-refusal.jpg](docs/evidence/live-a5-refusal.jpg) |
| Unit tests (green CI run, all suites) | [unit-tests-ci.log](docs/evidence/unit-tests-ci.log) |
| Agent scenarios on AWS: MCP-only, API-only, combined, confirmed payment, refusal, 429 (tool traces included) | [scenarios-aws.log](docs/evidence/scenarios-aws.log) · local run: [scenarios-local.log](docs/evidence/scenarios-local.log) |
| Gateway smoke test on AWS (protected route 401/200, 403, 429, closed ports) | [smoke-aws.log](docs/evidence/smoke-aws.log) · local: [smoke-local.log](docs/evidence/smoke-local.log) |
| Three MCP retrieval tests | [Inspector 1](docs/evidence/mcp-inspector-1-deadline.png) · [2](docs/evidence/mcp-inspector-2-installments.png) · [3](docs/evidence/mcp-inspector-3-late-fee.png) · [log](docs/evidence/mcp-retrieval-tests.log) |
| Confirmed simulated payment (web UI card → Paid) | [web-chat-payment.jpg](docs/evidence/web-chat-payment.jpg) · [agent-payment-flow.log](docs/evidence/agent-payment-flow.log) |
| Tool trace log line and request-id correlation | [agent-trace.log](docs/evidence/agent-trace.log) · [agent-tools-e2e.log](docs/evidence/agent-tools-e2e.log) |
| Turkish conversation | [agent-turkish-chat.log](docs/evidence/agent-turkish-chat.log) |
| Admin screen | [web-admin.jpg](docs/evidence/web-admin.jpg) |
| Swagger UI on AWS | [swagger-aws.jpg](docs/evidence/swagger-aws.jpg) |
| AWS resources (EC2, RDS, RDS firewall rule, host check) | [aws-ec2.jpg](docs/evidence/aws-ec2.jpg) · [aws-rds.jpg](docs/evidence/aws-rds.jpg) · [aws-rds-sg.jpg](docs/evidence/aws-rds-sg.jpg) · [aws-ec2-check.log](docs/evidence/aws-ec2-check.log) |

## 14. Cloud deployment

The whole stack runs on **AWS** (`eu-central-1`):

| Resource | Details |
|---|---|
| EC2 `t3.small` | Ubuntu 24.04, Elastic IP `18.153.247.247`. Runs Caddy, Kong, the web UI, the Tuition API, the agent and the MCP server with [docker-compose.prod.yml](docker-compose.prod.yml). |
| Amazon RDS | PostgreSQL 16, `db.t4g.micro`, not publicly accessible. Its security group only admits the EC2 instance on 5432, and connections use TLS (`sslmode=require`). |
| DNS and TLS | `tuition.cancolak.dev` → Elastic IP (Cloudflare DNS). Caddy gets and renews a Let's Encrypt certificate and redirects HTTP to HTTPS. |
| Secrets | `.env` on the server (mode 600), never committed. |

Deploying is `git clone` → `bash scripts/deploy.sh install` → `deploy.sh env` → `deploy.sh up --seed`. The step-by-step console walkthrough (EC2, Elastic IP, RDS, security groups, domain, verification, teardown) is in [docs/04_Deployment_Guide.md](docs/04_Deployment_Guide.md).

## 15. Costs

| Item | Cost |
|---|---|
| LLM (Gemini API) | **$0**: free tier, no billing account. The free tier is rate-limited per model and minute, so the agent falls back to lighter models. Unit tests and CI use a fake LLM, so testing costs nothing. |
| AWS EC2 `t3.small` + RDS `db.t4g.micro` + public IPv4 + 40 GB storage | about **$1.2 per day**, covered by AWS free-plan credits. A budget alert is set. Stop or delete the resources after the demo period ([guide §9](docs/04_Deployment_Guide.md#9-cost-and-teardown)). |
| Domain `cancolak.dev` | about $12 per year (optional; the IP address works too) |
| MCP search | $0: BM25 full-text index, no embedding API |

**Low-cost way to test:** run everything locally with `docker compose` (§10). Only the chat needs a free Gemini key, and every automated test runs offline.

## 16. Assumptions

1. **Term format** is `YYYY-FALL` or `YYYY-SPRING` (e.g. `2026-FALL`). Without `term`, Query Tuition returns the overall total and balance with a per-term breakdown.
2. **Money:** amounts are decimals with 2 places (`NUMERIC(12,2)`) and sent as strings. No rounding takes place, since inputs with more than 2 decimals are rejected. Each record has one currency (ISO-4217, default USD), and nothing is converted between currencies. An overall balance across terms in different currencies is refused (`409 MIXED_CURRENCIES`); query one term at a time.
3. **Payments:**
   - Partial and full payments are allowed.
   - Overpayment is rejected.
   - A repeated `transactionId` is rejected with 409 and never recorded twice.
   - A partial payment is **not** an installment plan (§3.4 of the policy).
   - Payments are simulated; no card data exists anywhere.
4. **Add Tuition duplicates:** the same student and term updates the existing record (200) instead of failing. The new amount may not be lower than what is already paid, the currency cannot change after payments, and the student must already exist.
5. **Batch upload:** each CSV row is handled independently. Invalid rows are reported with their row number and reason and do not stop the valid ones.
6. **Mobile limit:** 3 queries per student per calendar day (UTC), keyed by the student number in the path, enforced at the gateway. It applies whatever the client IP.
7. **Identity:** the system issues its own JWTs, and the demo users are seeded. In production this would be the university's SSO / OAuth 2.0 provider (e.g. Amazon Cognito).
8. **Policy interpretation:** late fees, installments, scholarships and refunds are explained from the policy document only, with section citations. No API changes data for them, and the assistant does not approve installment plans.
9. **API errors:** the API returns `{"error":{"code","message","details"}}`. Kong's own rejections (401 without a token, 429) use Kong's `{"message": …}` body. Status codes:

   | Code | Meaning |
   |---|---|
   | 400 | malformed request |
   | 401 | missing or invalid token |
   | 403 | wrong role or another student |
   | 404 | not found |
   | 409 | conflict (duplicate transaction, amount below paid, currency change) |
   | 422 | validation or business rule |
   | 429 | rate limit |

10. **Agent conversations** are kept in memory for 30 minutes of inactivity. A pending payment expires after 5 minutes.
11. **Deployment:** a single EC2 host with Docker Compose plus managed RDS is enough for this scale. There is no auto-scaling or multi-AZ setup.

## 17. Design decisions

| Decision | Why | Alternative considered |
|---|---|---|
| **Kong** instead of AWS API Gateway | Kong's `rate-limiting` can key on a value taken from the request path, so "3 per student per day" is plain configuration. Its `jwt` plugin and the same declarative file work identically locally, in CI and on AWS. | AWS API Gateway usage plans are keyed by API key, so a per-student limit for unauthenticated calls would need a Lambda authorizer plus DynamoDB counters, and the local setup would differ from the cloud. |
| **EC2 + Docker Compose + RDS** | One reproducible deploy command, a managed server database, low cost | ECS/Fargate or EKS: more infrastructure work than needed |
| **Self-issued JWT** | Simple and testable offline; the gateway can verify it | Cognito / university SSO: noted as the production path |
| **BM25 full-text index** | Enough for one policy document; deterministic, testable and free | Vector search: extra cost and complexity |
| **Confirmation enforced in code** | A prompt cannot bypass it | Prompt-only confirmation: unreliable |
| **Gemini** | Real function calling on a free tier, with fallback models | Paid models: cost |
| **Caddy in front of Kong** | Automatic Let's Encrypt certificates and renewal with a 10-line config | Certificates managed by hand in Kong |

The full ADRs are in [docs/02_Technical_Design.md §12](docs/02_Technical_Design.md#12-architecture-decision-records).

## 18. Repository layout and documents

```
services/tuition-api/   REST API (FastAPI) · Alembic migrations · seed · tests
services/mcp-server/    MCP server · policy document · index builder · tests
services/agent/         AI agent (Gemini function calling, MCP client) · tests
gateway/                Kong declarative config and image · Caddyfile
web/                    React web UI · tests
scripts/                smoke.sh · scenarios.py · deploy.sh
docs/                   SRS · technical design · test plan · deployment guide · ER · OpenAPI · MCP schema · evidence
docker-compose.yml      local stack        docker-compose.prod.yml   AWS stack
```

- [Requirements (SRS)](docs/01_SRS.md)
- [Technical design](docs/02_Technical_Design.md)
- [Test plan](docs/03_Test_Plan.md)
- [AWS deployment guide](docs/04_Deployment_Guide.md)
- [ER diagram](docs/er-diagram.png) · [OpenAPI spec](docs/openapi.json) · [MCP tool schema](docs/mcp-tool-schema.json)
- [Testing the MCP server with MCP Inspector](docs/mcp-inspector.md)
