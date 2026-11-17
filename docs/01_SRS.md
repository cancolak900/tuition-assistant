# Software Requirements Specification (SRS)
## AI Tuition Assistant

| Field | Value |
|---|---|
| Document ID | SRS-TUITION-01 |
| Version | 1.0 |
| Date | 2026-11-17 |
| Author | Can Çolak |
| Policy document | `University_Tuition_Policies.md` (UNI-TUITION-2026-01) |

---

## 1. Introduction

### 1.1 Purpose
This document defines **what** the AI Tuition Assistant system must do. It is the single source of truth for scope. Every requirement has an ID (`FR-xx`, `NFR-xx`) so that design (`02_Technical_Design.md`), tests (`03_Test_Plan.md`) and the README can trace back to it.

### 1.2 Product summary
A conversational assistant that lets university students ask about tuition deadlines, installment eligibility, payment rules, balances and payments. For each question, an LLM decides (through real tool/function calling) whether to:

- search the **tuition policy document** through an **MCP server** (policy questions),
- call the **Tuition REST API** through an **API Gateway** (live balances, payments),
- or **both** (questions that combine a student's balance with a policy).

The same REST APIs also serve three existing client applications: the **University Mobile App**, the **Banking App** and the **University Web Site – Admin**.

### 1.3 Definitions
| Term | Meaning |
|---|---|
| Term | Academic billing period, format `YYYY-FALL` / `YYYY-SPRING` (e.g. `2026-FALL`). |
| Tuition total | Assessed tuition for a student and term. |
| Balance | Tuition total minus the sum of successful payments for that student/term. |
| Agent | The backend service that talks to the LLM, executes tool calls and returns the grounded answer. |
| MCP | Model Context Protocol. The MCP server exposes `search_tuition_policies(query)`. |
| Gateway | API Gateway that every REST call, including the agent's calls, passes through. |
| Tool trace | Ordered log of tool name, input, result and final answer for each chat turn. |

### 1.4 Out of scope
- Real card or money processing. Payments are simulated records only.
- Installment plan approval workflow, late-fee posting and refund processing. The policy document describes these, but no API is required for them.
- Load testing.
- Pixel-perfect visual polish. The UI is designed (Stitch → Figma) for clarity, but functionality takes priority over appearance.

---

## 2. Stakeholders and actors

| Actor | Description | Auth role |
|---|---|---|
| Student (via AI chat) | Asks questions, checks own balance, pays own tuition after confirmation. | `student` |
| Mobile App user | Anonymous quick balance check, limited to 3 calls per student per day. | none |
| Banking App | Third-party bank client that queries and pays tuition on behalf of students. | `bank` |
| University Admin | Creates/updates tuition (single + CSV batch) and views unpaid students. | `admin` |
| Reviewer | Reproduces results from the README, test data and deployed URLs. | n/a |

---

## 3. Functional requirements

### 3.1 Tuition REST API

| ID | Requirement | Client | Auth | Paging |
|---|---|---|---|---|
| FR-01 | **Query Tuition (mobile)**: given `studentNo` and an optional `term`, return tuition total and balance. Without `term`, return the overall total/balance plus a per-term breakdown. | Mobile App | No | No |
| FR-02 | FR-01 is limited to **3 calls per student per day**. The limit is keyed by `studentNo`, not by client IP. The 4th call returns `429` with a JSON error body. | Mobile App | — | — |
| FR-03 | **Query Tuition (banking)**: same contract as FR-01, but requires authentication. | Banking App, Agent | Yes | No |
| FR-04 | **Pay Tuition**: input `studentNo, term, amount, transactionId`; output payment status, paid amount, remaining balance. Records a simulated full or partial payment. | Banking App, Agent | Yes | No |
| FR-05 | Pay Tuition **rejects a duplicate `transactionId`** (`409`). | — | — | — |
| FR-06 | Pay Tuition **rejects an amount ≤ 0 or greater than the current balance** (`422`). Overpayment is not supported. | — | — | — |
| FR-07 | **Add Tuition**: input `studentNo, term, amount, currency`; creates or updates the tuition for that student and term. Duplicate rule: the same `(studentNo, term)` updates the existing record; an update that would set the amount below the amount already paid is rejected (`409`). | Admin | Yes | No |
| FR-08 | **Add Tuition – Batch**: upload a CSV with header `studentNo,term,amount,currency`. Each row is processed with the same rules as FR-07. Returns `successCount`, `failureCount` and per-row errors (row number + reason). One bad row does not roll back the good rows. | Admin | Yes | No |
| FR-09 | **Unpaid Tuition Status**: input `term, page, pageSize`; returns a paged list of students with balance > 0 for that term, plus paging metadata (`page, pageSize, totalItems, totalPages`). | Admin | Yes | **Yes** |
| FR-10 | **Login**: issues a JWT for a username/password. Claims: `sub` (user id), `role` (`student`/`bank`/`admin`), `studentNo` (student role only), `exp`. Demo users are seeded. | All | — | — |

### 3.2 Authorization rules

| ID | Requirement |
|---|---|
| FR-11 | All payment, account-detail and administrative operations require a valid JWT. |
| FR-12 | A `student` token may only read or pay **its own** `studentNo`. A request for another student returns `403`, even if the number was supplied in a chat prompt. |
| FR-13 | A `bank` token may query and pay for any student. An `admin` token may use the admin endpoints. Any other role/endpoint combination returns `403`. |

### 3.3 MCP server (policy search)

| ID | Requirement |
|---|---|
| FR-20 | `University_Tuition_Policies.md` is split into searchable chunks, one per numbered section (e.g. `3.2`). Each chunk keeps its section ID, heading, parent heading and the document ID. |
| FR-21 | The index is built **once**, before queries (build step / service startup). It is **not** rebuilt for each question. |
| FR-22 | A real MCP SDK server exposes the tool `search_tuition_policies(query: str, top_k: int = 3)`. |
| FR-23 | The tool returns JSON: `{ document, documentId, matches: [{ section, heading, text, score }] }`, matching the format in section 9 of the policy document. |
| FR-24 | Three distinct retrieval queries are demonstrated with logged results, e.g. *deadline*, *installments*, *late fee*. |

### 3.4 AI Agent

| ID | Requirement |
|---|---|
| FR-30 | The agent uses **real LLM function calling** (Gemini). There is no keyword-based routing. The LLM picks from the declared tools: `search_tuition_policies` (MCP), `query_tuition` (REST) and `pay_tuition` (REST). |
| FR-31 | The agent, not the LLM, executes the tool calls: MCP calls go through the MCP client, REST calls go through the **API Gateway**. The tool results are sent back to the LLM, which writes the final answer. |
| FR-32 | Answers that use policy text cite the **section numbers** (e.g. "see §3.2"). |
| FR-33 | **Payment confirmation**: when the LLM requests `pay_tuition`, the agent **does not execute it**. It creates a *pending action* and shows student, term, amount and current balance. The payment API is called only after the user explicitly confirms it (a Confirm button / `POST /confirm`). A question such as "Can I pay $500?" is never treated as consent. |
| FR-34 | The agent calls the REST APIs with the **logged-in user's JWT**. It has no privileged credential of its own, so FR-12 also holds inside chat. |
| FR-35 | Every chat turn produces a **tool trace** (tool name, input, result, final answer). The trace is shown in the UI and written to logs. |
| FR-36 | Three scenarios are demonstrated: (1) MCP-only, (2) REST-only, (3) combined MCP + REST, plus (4) a confirmed simulated payment. |
| FR-37 | The agent never claims that a payment succeeded unless the Pay Tuition API returned success. |

### 3.5 Web UI

| ID | Requirement |
|---|---|
| FR-40 | Login screen (demo users listed in the README). |
| FR-41 | Chat screen with message history, a **tool trace panel** and a payment **confirmation card** (Confirm / Cancel). |
| FR-42 | Admin screen: single tuition add, CSV upload with a result summary, and a paged unpaid list. |
| FR-43 | Visual design is made in Google Stitch, refined in Figma, then implemented. |

---

## 4. Non-functional requirements

| ID | Category | Requirement |
|---|---|---|
| NFR-01 | Gateway | **All** REST operations, including agent calls, are routed through the API Gateway. Backend service ports are not publicly exposed. |
| NFR-02 | Gateway | Versioned public routes (`/api/v1/...`). The gateway URL, route mappings and one sample error response are documented. |
| NFR-03 | Gateway | Authentication and rate limits are enforced consistently at the gateway; FR-02 is keyed by student identity. |
| NFR-04 | Versioning | Every API path carries a major version (`v1`). A future `v2` can be added side by side. |
| NFR-05 | Docs | An OpenAPI spec and Swagger UI are available. The exported `openapi.json` is committed to the repo. |
| NFR-06 | Database | PostgreSQL server database (AWS RDS). SQLite is not used. An ER diagram is provided. |
| NFR-07 | Security | Passwords are hashed (bcrypt). JWTs are signed and expire (60 min). Secrets come from environment variables and are never committed. |
| NFR-08 | Reliability | Payments are idempotent through a unique `transactionId`; agent retries reuse the same ID. |
| NFR-09 | Money | Amounts are stored as `NUMERIC(12,2)` and handled as `Decimal`. Currency is an ISO-4217 code (default `USD`). |
| NFR-10 | Testing | Automated unit tests (pytest) cover every REST operation with at least one success test and one failure/edge test. Tests run without the cloud and without a live LLM. |
| NFR-11 | Architecture | Service-oriented: separate deployable services for the Tuition API, MCP server, Agent and Web UI. |
| NFR-12 | Deployment | API, MCP server, gateway and DB are deployed on AWS. Local deployment is only the documented fallback. |
| NFR-13 | Cost | The LLM runs on the Gemini free tier. AWS costs stay within free-plan credits. Costs are documented in the README. |
| NFR-14 | Reproducibility | A reviewer can reproduce results from the README using seed data, demo users and step-by-step instructions. |

---

## 5. Acceptance scenarios (demo script)

| # | User says (as student `S1001`) | Expected tools | Expected outcome |
|---|---|---|---|
| A1 | "When is the Fall payment deadline?" | `search_tuition_policies` | "September 30, 2026 (§2.1)". |
| A2 | "What is my balance?" | `query_tuition` | Live total and balance from the DB. |
| A3 | "Can I pay my outstanding balance in installments?" | `query_tuition` + `search_tuition_policies` | Balance ≥ $300 → eligible to *request* up to 3 installments (§3.1, §3.2), approval not guaranteed (§3.4). |
| A4 | "Pay $500 of my Fall tuition" → user clicks **Confirm** | `pay_tuition` (after confirmation) | Payment recorded, new balance shown. |
| A5 | "What is the balance of student S1002?" | `query_tuition` → 403 | Assistant refuses; no data leaked. |
| A6 | Mobile query called 4× in a day for the same student | — | 4th call → `429` from the gateway. |

---

## 6. Requirement coverage by component

| Component | Requirements |
|---|---|
| REST APIs & business logic | FR-01…FR-10, NFR-04, NFR-05, NFR-08, NFR-09 |
| AI Agent / LLM tool calling | FR-30…FR-37 |
| MCP server & indexing | FR-20…FR-24 |
| API Gateway | NFR-01…NFR-03, FR-02 |
| Database & authentication | FR-10…FR-13, NFR-06, NFR-07 |
| Cloud deployment | NFR-12, NFR-13 |
| Testing & documentation | NFR-10, NFR-14, README deliverables |

## 7. Assumptions (to be copied into the README)
1. **Term** format is `YYYY-FALL` / `YYYY-SPRING`. Without a `term`, Query Tuition returns the overall total/balance with a per-term breakdown.
2. **Overpayment** is rejected. A partial payment is never treated as installment approval (§3.4).
3. **Add Tuition duplicates** update the existing amount and currency; the new amount may not be lower than the amount already paid.
4. The **mobile rate limit** uses the calendar day in UTC and is keyed by the `studentNo` in the request path.
5. **Identity**: the system issues its own JWTs (demo users are seeded). In production this would be the university SSO / OAuth 2.0 provider.
6. Only one currency is used per tuition record; amounts are not converted between currencies.
7. Late fees, installment plans and refunds are explained from the policy document only; no API changes data for them.
