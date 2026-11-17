import { request } from "./client";

/** Agent API (through Kong at /api/v1/agent). Shapes mirror services/agent/app/schemas.py. */

export interface TraceStep {
  step: number;
  tool: string;
  kind: "mcp" | "rest" | "local";
  input: Record<string, unknown>;
  output: unknown;
  status: "ok" | "error";
  durationMs: number;
}

export interface PendingAction {
  actionId: string;
  type: "pay_tuition";
  studentNo: string;
  term: string;
  amount: string;
  currency: string;
  balance: string;
  balanceAfter: string;
  expiresAt: string;
}

export interface PaymentResult {
  status: string;
  transactionId: string;
  studentNo: string;
  term: string;
  paidAmount: string;
  totalPaid: string;
  remainingBalance: string;
  currency: string;
}

export interface ChatResponse {
  sessionId: string;
  reply: string;
  trace: TraceStep[];
  pendingAction: PendingAction | null;
}

export interface ConfirmResponse {
  sessionId: string;
  reply: string;
  trace: TraceStep[];
  payment: PaymentResult | null;
  pendingAction: PendingAction | null;
}

export function sendMessage(message: string, sessionId: string | null): Promise<ChatResponse> {
  return request<ChatResponse>("/agent/chat", { method: "POST", body: sessionId ? { sessionId, message } : { message } });
}

export function decide(sessionId: string, actionId: string, decision: "confirm" | "cancel"): Promise<ConfirmResponse> {
  return request<ConfirmResponse>("/agent/confirm", { method: "POST", body: { sessionId, actionId, decision } });
}
