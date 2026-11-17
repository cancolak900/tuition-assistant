import type { TraceStep } from "../../api/agent";

/** "$5,000.00" for USD, "5,000.00 EUR" style for others (amounts arrive as decimal strings). */
export function money(amount: string | number, currency = "USD"): string {
  const value = typeof amount === "number" ? amount : Number(amount);
  if (!Number.isFinite(value)) return `${amount} ${currency}`;
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency, minimumFractionDigits: 2 }).format(value);
  } catch {
    return `${value.toFixed(2)} ${currency}`;
  }
}

export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

export function countdown(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);

/** One short phrase per trace step, like the Figma trace lines ("→ balance $5,000.00"). */
export function summarize(step: TraceStep): string {
  const out = step.output;
  if (step.status === "error" && isObj(out) && isObj(out.error)) return String(out.error.code ?? "error");
  if (!isObj(out)) return step.status;
  if (step.tool === "search_tuition_policies" && Array.isArray(out.matches)) {
    const sections = (out.matches as Obj[]).map((m) => `§${m.section}`);
    return sections.length ? sections.join(", ") : "no matching section";
  }
  if (step.tool === "query_tuition" && "balance" in out) return `balance ${money(String(out.balance), String(out.currency ?? "USD"))}`;
  if ("status" in out) return String(out.status);
  return "ok";
}

export function compactJson(value: unknown): string {
  return JSON.stringify(value)?.replace(/":/g, '": ').replace(/,"/g, ', "') ?? "";
}
