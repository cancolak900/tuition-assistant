import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../App";
import { AuthProvider } from "../auth/AuthContext";
import { saveSession } from "../auth/session";
import { summarize } from "../components/chat/format";
import { fakeJwt, installFakeApi, type Call } from "../test/fakeApi";

const policyStep = {
  step: 1, tool: "search_tuition_policies", kind: "mcp", status: "ok", durationMs: 30, input: { query: "fall payment deadline" },
  output: { document: "p.md", documentId: "D", matches: [{ section: "2.1", heading: "Fall term", text: "Due September 30, 2026.", score: 7 }] },
};
const balanceStep = {
  step: 1, tool: "query_tuition", kind: "rest", status: "ok", durationMs: 14, input: { studentNo: "S1001", term: "2026-FALL", reason: "balance check before payment" },
  output: { studentNo: "S1001", balance: "5000.00", currency: "USD" },
};
const pending = (id = "a1", minutes = 5) => ({
  actionId: id, type: "pay_tuition", studentNo: "S1001", term: "2026-FALL", amount: "500.00", currency: "USD",
  balance: "5000.00", balanceAfter: "4500.00", expiresAt: new Date(Date.now() + minutes * 60_000).toISOString(),
});
const paid = {
  status: "SUCCESS", transactionId: "AGT-1", studentNo: "S1001", term: "2026-FALL", paidAmount: "500.00",
  totalPaid: "500.00", remainingBalance: "4500.00", currency: "USD",
};

function renderChat() {
  saveSession({
    token: fakeJwt({ sub: "1", role: "student", exp: Math.floor(Date.now() / 1000) + 3600 }),
    user: { userId: 1, username: "s1001", role: "student", studentNo: "S1001" },
    expiresAt: Date.now() + 3_600_000,
  });
  return render(
    <MemoryRouter initialEntries={["/chat"]}>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </MemoryRouter>,
  );
}

function type(text: string) {
  const box = screen.getByLabelText("Message");
  fireEvent.change(box, { target: { value: text } });
  fireEvent.keyDown(box, { key: "Enter" });
}

const chatCalls = (calls: Call[]) => calls.filter((c) => c.path === "/api/v1/agent/chat");
const confirmCalls = (calls: Call[]) => calls.filter((c) => c.path === "/api/v1/agent/confirm");

beforeEach(() => sessionStorage.clear());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("chat screen", () => {
  it("sends a message, shows the plain-text reply and a collapsible tool trace", async () => {
    const calls = installFakeApi({
      "POST /api/v1/agent/chat": () => ({ status: 200, body: { sessionId: "s1", reply: "The Fall deadline is September 30, 2026 (§2.1).", trace: [policyStep], pendingAction: null } }),
    });
    renderChat();
    type("When is the Fall payment deadline?");
    expect(await screen.findByText("The Fall deadline is September 30, 2026 (§2.1).")).toBeTruthy();
    expect(chatCalls(calls)[0].body).toEqual({ message: "When is the Fall payment deadline?" });
    const toggle = screen.getByRole("button", { name: /Tool trace · 1 step · 30 ms/ });
    expect(screen.queryByRole("list", { name: "Tool trace" })).toBeNull(); // closed by default
    fireEvent.click(toggle);
    const trace = screen.getByRole("list", { name: "Tool trace" });
    expect(trace.textContent).toContain("search_tuition_policies");
    expect(trace.textContent).toContain("§2.1");
  });

  it("keeps the agent session id for the next message", async () => {
    const calls = installFakeApi({ "POST /api/v1/agent/chat": () => ({ status: 200, body: { sessionId: "s1", reply: "ok", trace: [], pendingAction: null } }) });
    renderChat();
    type("first");
    await screen.findByText("ok");
    type("second");
    await waitFor(() => expect(chatCalls(calls)).toHaveLength(2));
    expect(chatCalls(calls)[1].body).toEqual({ sessionId: "s1", message: "second" });
  });

  it("shows the confirmation card and pays only after Confirm", async () => {
    const calls = installFakeApi({
      "POST /api/v1/agent/chat": () => ({ status: 200, body: { sessionId: "s1", reply: "Please review the payment below.", trace: [balanceStep], pendingAction: pending() } }),
      "POST /api/v1/agent/confirm": () => ({ status: 200, body: { sessionId: "s1", reply: "Payment successful: 500.00 USD for 2026-FALL.", trace: [], payment: paid, pendingAction: null } }),
    });
    renderChat();
    type("Pay $500 of my Fall tuition");
    const card = await screen.findByRole("region", { name: "Confirm payment" });
    expect(within(card).getByText("$500.00")).toBeTruthy();
    expect(within(card).getByText("$4,500.00")).toBeTruthy();
    expect(within(card).getByText(/Expires in 0[45]:/)).toBeTruthy();
    expect(confirmCalls(calls)).toHaveLength(0); // nothing paid yet
    fireEvent.click(within(card).getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("Payment successful: 500.00 USD for 2026-FALL.")).toBeTruthy();
    expect(confirmCalls(calls).map((c) => c.body)).toEqual([{ sessionId: "s1", actionId: "a1", decision: "confirm" }]);
    expect(within(card).getByText("Paid")).toBeTruthy();
    expect(within(card).queryByRole("button", { name: "Confirm" })).toBeNull(); // cannot be pressed twice
  });

  it("cancels from the card's chip", async () => {
    const calls = installFakeApi({
      "POST /api/v1/agent/chat": () => ({ status: 200, body: { sessionId: "s1", reply: "Review it.", trace: [], pendingAction: pending() } }),
      "POST /api/v1/agent/confirm": () => ({ status: 200, body: { sessionId: "s1", reply: "Payment cancelled.", trace: [], payment: null, pendingAction: null } }),
    });
    renderChat();
    type("pay 500");
    await screen.findByRole("region", { name: "Confirm payment" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel payment" }));
    expect(await screen.findByText("Payment cancelled.")).toBeTruthy();
    expect(confirmCalls(calls)[0].body).toMatchObject({ decision: "cancel" });
    expect(screen.getByText("Cancelled")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Cancel payment" })).toBeNull();
  });

  it("keeps the card when the payment result is unknown, so Confirm can be retried safely", async () => {
    installFakeApi({
      "POST /api/v1/agent/chat": () => ({ status: 200, body: { sessionId: "s1", reply: "Review it.", trace: [], pendingAction: pending() } }),
      "POST /api/v1/agent/confirm": () => ({ status: 200, body: { sessionId: "s1", reply: "I could not reach the payment service.", trace: [], payment: null, pendingAction: pending() } }),
    });
    renderChat();
    type("pay 500");
    const card = await screen.findByRole("region", { name: "Confirm payment" });
    fireEvent.click(within(card).getByRole("button", { name: "Confirm" }));
    await screen.findByText("I could not reach the payment service.");
    expect(within(card).getByRole("button", { name: "Confirm" })).toBeTruthy();
  });

  it("marks an expired card when the agent answers 410", async () => {
    installFakeApi({
      "POST /api/v1/agent/chat": () => ({ status: 200, body: { sessionId: "s1", reply: "Review it.", trace: [], pendingAction: pending() } }),
      "POST /api/v1/agent/confirm": () => ({ status: 410, body: { error: { code: "ACTION_EXPIRED", message: "This payment confirmation expired." } } }),
    });
    renderChat();
    type("pay 500");
    const card = await screen.findByRole("region", { name: "Confirm payment" });
    fireEvent.click(within(card).getByRole("button", { name: "Confirm" }));
    expect(await within(card).findByText("Expired")).toBeTruthy();
  });

  it("shows a card as expired once its time is over", async () => {
    installFakeApi({ "POST /api/v1/agent/chat": () => ({ status: 200, body: { sessionId: "s1", reply: "Review it.", trace: [], pendingAction: pending("a1", -1) } }) });
    renderChat();
    type("pay 500");
    const card = await screen.findByRole("region", { name: "Confirm payment" });
    expect(within(card).getByText("Expired")).toBeTruthy();
    expect(within(card).queryByRole("button", { name: "Confirm" })).toBeNull();
  });

  it("marks the older card as replaced when a new one arrives", async () => {
    let n = 0;
    installFakeApi({ "POST /api/v1/agent/chat": () => ({ status: 200, body: { sessionId: "s1", reply: `card ${++n}`, trace: [], pendingAction: pending(`a${n}`) } }) });
    renderChat();
    type("pay 500");
    await screen.findByText("card 1");
    type("pay 100 instead");
    await screen.findByText("card 2");
    const cards = screen.getAllByRole("region", { name: "Confirm payment" });
    expect(within(cards[0]).getByText("Replaced")).toBeTruthy();
    expect(within(cards[1]).getByRole("button", { name: "Confirm" })).toBeTruthy();
  });

  it("starts a new agent session when the old one expired", async () => {
    const calls = installFakeApi({
      "POST /api/v1/agent/chat": (c) =>
        (c.body as { sessionId?: string }).sessionId === "old"
          ? { status: 404, body: { error: { code: "SESSION_NOT_FOUND", message: "expired" } } }
          : { status: 200, body: { sessionId: "new", reply: "fresh answer", trace: [], pendingAction: null } },
    });
    sessionStorage.setItem("tuition-assistant.chat.1", JSON.stringify({ sessionId: "old", items: [] }));
    renderChat();
    type("hello again");
    expect(await screen.findByText("fresh answer")).toBeTruthy();
    expect(chatCalls(calls).map((c) => (c.body as { sessionId?: string }).sessionId)).toEqual(["old", undefined]);
  });

  it("shows a busy model as a readable message and keeps the input usable", async () => {
    installFakeApi({ "POST /api/v1/agent/chat": () => ({ status: 503, body: { error: { code: "LLM_BUSY", message: "busy" } } }) });
    renderChat();
    type("hi");
    expect(await screen.findByText("The assistant is busy right now. Please try again in a minute.")).toBeTruthy();
    expect((screen.getByLabelText("Message") as HTMLTextAreaElement).disabled).toBe(false);
  });

  it("sends a suggestion chip as a message", async () => {
    const calls = installFakeApi({ "POST /api/v1/agent/chat": () => ({ status: 200, body: { sessionId: "s1", reply: "ok", trace: [], pendingAction: null } }) });
    renderChat();
    fireEvent.click(screen.getByRole("button", { name: "What is my balance?" }));
    await screen.findByText("ok");
    expect(chatCalls(calls)[0].body).toEqual({ message: "What is my balance?" });
  });

  it("scrolls to the newest message after sending and when the answer arrives", async () => {
    const scrollTo = vi.fn();
    vi.stubGlobal("scrollTo", scrollTo);
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => (cb(0), 1));
    installFakeApi({ "POST /api/v1/agent/chat": () => ({ status: 200, body: { sessionId: "s1", reply: "answer", trace: [], pendingAction: null } }) });
    renderChat();
    type("hello");
    await screen.findByText("answer");
    expect(scrollTo.mock.calls.length).toBeGreaterThanOrEqual(2); // own message, then the reply
    expect(scrollTo).toHaveBeenLastCalledWith({ top: document.documentElement.scrollHeight, behavior: "smooth" });
  });

  it("does not pull a reader who scrolled up back to the bottom", async () => {
    const scrollTo = vi.fn();
    vi.stubGlobal("scrollTo", scrollTo);
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => (cb(0), 1));
    let answer!: (v: unknown) => void;
    installFakeApi({
      "POST /api/v1/agent/chat": () =>
        new Promise((resolve) => {
          answer = () => resolve({ status: 200, body: { sessionId: "s1", reply: "late answer", trace: [], pendingAction: null } });
        }),
    });
    renderChat();
    type("hello");
    await waitFor(() => expect(answer).toBeDefined());
    const callsAfterSend = scrollTo.mock.calls.length;
    // The reader scrolls up to an older message while the assistant is still thinking.
    Object.defineProperty(document.documentElement, "scrollHeight", { configurable: true, value: 5000 });
    window.dispatchEvent(new Event("scroll"));
    answer(null);
    await screen.findByText("late answer");
    expect(scrollTo.mock.calls.length).toBe(callsAfterSend);
    Object.defineProperty(document.documentElement, "scrollHeight", { configurable: true, value: 0 });
  });

  it("summarizes trace steps like the Figma trace lines", () => {
    expect(summarize(balanceStep as never)).toBe("balance $5,000.00");
    expect(summarize(policyStep as never)).toBe("§2.1");
    expect(summarize({ ...balanceStep, status: "error", output: { error: { code: "FORBIDDEN_OTHER_STUDENT" } } } as never)).toBe("FORBIDDEN_OTHER_STUDENT");
    expect(summarize({ ...balanceStep, tool: "pay_tuition", output: { status: "AWAITING_USER_CONFIRMATION" } } as never)).toBe("AWAITING_USER_CONFIRMATION");
  });
});
