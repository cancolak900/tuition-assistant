#!/usr/bin/env python3
"""Run the assistant scenarios A1-A6 (docs/01_SRS.md) against a running stack, through the gateway.

Only the Python standard library is used, so no install is needed.

    python scripts/scenarios.py                         # all scenarios against http://localhost
    python scripts/scenarios.py --only A1,A3            # some scenarios
    python scripts/scenarios.py --yes                   # A4 confirms the payment without asking
    python scripts/scenarios.py --chat                  # free chat as the logged-in student
    python scripts/scenarios.py --base-url http://<host> --user s1002 --password 'Pass1002!'

A4 makes a real (simulated) payment when confirmed; without --yes it asks first.
A6 uses one of the extra seed students (default S1020) so the demo logins keep their mobile quota.
Exit code: 0 when every check passed, 1 otherwise.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from decimal import Decimal

TIMEOUT = 120  # an answer may need several LLM rounds
USE_COLOR = sys.stdout.isatty()


def color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.token: str | None = None

    def call(self, method: str, path: str, body: dict | None = None, auth: bool = True) -> tuple[int, dict, dict]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if auth and self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
                return res.status, json.loads(res.read() or b"null"), dict(res.headers)
        except urllib.error.HTTPError as err:
            raw = err.read()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {"raw": raw.decode(errors="replace")}
            return err.code, payload, dict(err.headers)

    def login(self, user: str, password: str) -> None:
        status, body, _ = self.call("POST", "/api/v1/auth/login", {"username": user, "password": password}, auth=False)
        if status != 200:
            sys.exit(f"Login failed ({status}): {body}")
        self.token = body["accessToken"]

    def chat(self, message: str, session_id: str | None) -> tuple[int, dict]:
        status, body, _ = self.call("POST", "/api/v1/agent/chat", {"message": message, **({"sessionId": session_id} if session_id else {})})
        return status, body

    def confirm(self, session_id: str, action_id: str, decision: str) -> tuple[int, dict]:
        status, body, _ = self.call("POST", "/api/v1/agent/confirm", {"sessionId": session_id, "actionId": action_id, "decision": decision})
        return status, body


def show_trace(trace: list[dict]) -> None:
    for s in trace:
        mark = color("ok", "32") if s["status"] == "ok" else color("error", "31")
        print(f"    [{s['step']}] {s['kind']:<5} {s['tool']:<24} {mark:<5} {s['durationMs']:>5} ms  input={json.dumps(s['input'], ensure_ascii=False)}")
        if s["status"] == "error":
            print(f"        -> {json.dumps(s['output'], ensure_ascii=False)}")


def show_turn(question: str, status: int, body: dict) -> None:
    print(color(f"\n  You: {question}", "1"))
    if status != 200:
        print(color(f"  HTTP {status}: {json.dumps(body, ensure_ascii=False)}", "31"))
        return
    print("  Tool trace:")
    if body["trace"]:
        show_trace(body["trace"])
    else:
        print("    (no tools)")
    print(color("  Assistant: ", "36") + body["reply"].replace("\n", "\n             "))


class Runner:
    def __init__(self, api: Api, args: argparse.Namespace) -> None:
        self.api, self.args = api, args
        self.results: list[tuple[str, bool, str]] = []

    def check(self, scenario: str, ok: bool, what: str) -> None:
        self.results.append((scenario, ok, what))
        print(f"  {color('PASS', '32') if ok else color('FAIL', '31')}  {what}")

    def ask(self, scenario: str, question: str, session_id: str | None = None) -> dict:
        status, body = self.api.chat(question, session_id)
        show_turn(question, status, body)
        if status != 200:
            self.check(scenario, False, f"chat answered (HTTP {status})")
            return {}
        return body

    @staticmethod
    def kinds(body: dict) -> list[tuple[str, str]]:
        return [(s["tool"], s["status"]) for s in body.get("trace", [])]

    def a1(self) -> None:
        body = self.ask("A1", "When is the Fall payment deadline?")
        if body:
            self.check("A1", ("search_tuition_policies", "ok") in self.kinds(body), "policy searched over MCP")
            self.check("A1", "September 30" in body["reply"] and "2.1" in body["reply"], "answer is September 30, 2026 with §2.1")

    def a2(self) -> None:
        body = self.ask("A2", "What is my balance?")
        if body:
            rest = [s for s in body["trace"] if s["tool"] == "query_tuition" and s["status"] == "ok"]
            self.check("A2", bool(rest), "live balance read over REST (through the gateway)")
            if rest:
                balance = rest[-1]["output"]["balance"]
                self.check("A2", balance.split(".")[0] in body["reply"].replace(",", ""), f"answer shows the live balance ({balance})")

    def a3(self) -> None:
        body = self.ask("A3", "Can I pay my outstanding balance in installments?")
        if body:
            tools = {t for t, st in self.kinds(body) if st == "ok"}
            self.check("A3", {"search_tuition_policies", "query_tuition"} <= tools, "both tools used (policy + live balance)")
            self.check("A3", re.search(r"3\.\d", body["reply"]) is not None, "answer cites a §3.x installment section")

    def a4(self) -> None:
        amount = self.args.amount
        body = self.ask("A4", f"Pay ${amount} of my Fall tuition.")
        pending = body.get("pendingAction") if body else None
        self.check("A4", pending is not None, "a confirmation card (pendingAction) is returned, nothing paid yet")
        if not pending:
            return
        print(f"\n  Confirmation card: pay {pending['amount']} {pending['currency']} for {pending['term']} "
              f"(balance {pending['balance']} -> {pending['balanceAfter']}), expires {pending['expiresAt']}")
        decision = "confirm" if self.args.yes else ("confirm" if input("  Confirm this payment? [y/N] ").strip().lower() in ("y", "yes", "e", "evet") else "cancel")
        status, out = self.api.confirm(body["sessionId"], pending["actionId"], decision)
        print(f"\n  /confirm decision={decision} -> HTTP {status}")
        show_trace(out.get("trace", []))
        print(color("  Assistant: ", "36") + out.get("reply", json.dumps(out)))
        if decision == "cancel":
            self.check("A4", status == 200 and out.get("payment") is None, "cancelled: nothing was paid")
            return
        payment = out.get("payment") or {}
        self.check("A4", payment.get("status") == "SUCCESS", "payment recorded (status SUCCESS)")
        if payment:
            expected = Decimal(pending["balance"]) - Decimal(pending["amount"])
            self.check("A4", Decimal(payment["remainingBalance"]) == expected, f"new balance shown ({payment['remainingBalance']})")
            _, again = self.api.confirm(body["sessionId"], pending["actionId"], "confirm")
            self.check("A4", again == out, "pressing Confirm again returns the same result (no second payment)")

    def a5(self) -> None:
        body = self.ask("A5", "What is the balance of student S1002?")
        if body:
            denied = [s for s in body["trace"] if s["tool"] == "query_tuition" and s["status"] == "error"]
            leaked = any(s["tool"] == "query_tuition" and s["status"] == "ok" and s["output"].get("studentNo") == "S1002" for s in body["trace"])
            self.check("A5", not leaked, "no data of S1002 was returned")
            self.check("A5", bool(denied) or not any(t == "query_tuition" for t, _ in self.kinds(body)),
                       "the request was refused (403 from the API) or not attempted")

    def a6(self) -> None:
        student = self.args.mobile_student
        print(color(f"\n  Mobile query for {student} (no login, limit 3 per student per day at the gateway)", "1"))
        statuses = []
        for i in range(1, 6):  # stops at the first 429
            status, body, headers = self.api.call("GET", f"/api/v1/mobile/tuition/{student}", auth=False)
            remaining = headers.get("X-RateLimit-Remaining-Day", "-")
            print(f"    call {i}: HTTP {status}  remaining today={remaining}  {json.dumps(body, ensure_ascii=False)[:90]}")
            statuses.append(status)
            if status == 429:
                break
        self.check("A6", statuses[-1] == 429, "the gateway answers 429 once the daily limit is used up")
        if statuses.count(200) == 3:
            self.check("A6", len(statuses) == 4, "exactly the 4th call of the day is refused")
        else:
            print(f"    (this student had already used {3 - statuses.count(200)} of today's calls; use --mobile-student S10xx for a fresh one)")

    def summary(self) -> int:
        failed = [r for r in self.results if not r[1]]
        print(color(f"\n{len(self.results) - len(failed)}/{len(self.results)} checks passed", "32" if not failed else "31"))
        for scenario, _, what in failed:
            print(f"  {scenario}: {what}")
        print("Note: the assistant's wording comes from the LLM, so a text check can fail on an otherwise correct answer. Read the reply.")
        return 1 if failed else 0


def free_chat(api: Api) -> None:
    print("Free chat. Type a message, 'exit' to quit. A payment card asks for confirmation here.")
    session_id = None
    while True:
        try:
            message = input(color("\nYou: ", "1")).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if message.lower() in ("exit", "quit", "q", "çık"):
            break
        if not message:
            continue
        status, body = api.chat(message, session_id)
        if status != 200:
            print(color(f"HTTP {status}: {json.dumps(body, ensure_ascii=False)}", "31"))
            continue
        session_id = body["sessionId"]
        show_trace(body["trace"])
        print(color("Assistant: ", "36") + body["reply"])
        pending = body.get("pendingAction")
        if pending:
            answer = input(f"Pay {pending['amount']} {pending['currency']} for {pending['term']}? [y/N] ").strip().lower()
            decision = "confirm" if answer in ("y", "yes", "e", "evet") else "cancel"
            _, out = api.confirm(session_id, pending["actionId"], decision)
            show_trace(out.get("trace", []))
            print(color("Assistant: ", "36") + out.get("reply", json.dumps(out)))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost", help="gateway URL (default http://localhost)")
    parser.add_argument("--user", default="s1001")
    parser.add_argument("--password", default="Pass1001!")
    parser.add_argument("--only", default="A1,A2,A3,A4,A5,A6", help="comma-separated scenarios, e.g. A1,A4")
    parser.add_argument("--amount", default="500", help="A4 payment amount (default 500)")
    parser.add_argument("--yes", action="store_true", help="A4: confirm the payment without asking")
    parser.add_argument("--mobile-student", default="S1020", help="A6 student number (default S1020)")
    parser.add_argument("--chat", action="store_true", help="free chat instead of the scenarios")
    args = parser.parse_args()

    api = Api(args.base_url)
    api.login(args.user, args.password)
    print(f"Logged in as {args.user} at {api.base}")
    if args.chat:
        free_chat(api)
        return 0

    runner = Runner(api, args)
    titles = {"A1": "policy question (MCP only)", "A2": "balance question (REST only)", "A3": "installments (policy + balance)",
              "A4": "payment with confirmation", "A5": "another student's data (must refuse)", "A6": "mobile daily limit (gateway 429)"}
    for name in [s.strip().upper() for s in args.only.split(",") if s.strip()]:
        if name not in titles:
            sys.exit(f"Unknown scenario {name}; choose from {', '.join(titles)}")
        print(color(f"\n=== {name}: {titles[name]} " + "=" * (60 - len(titles[name])), "35"))
        getattr(runner, name.lower())()
    return runner.summary()


if __name__ == "__main__":
    sys.exit(main())
