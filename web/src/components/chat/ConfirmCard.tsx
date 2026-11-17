import { useEffect, useState } from "react";
import type { PendingAction } from "../../api/agent";
import { Button, cn } from "../ui";
import { countdown, money } from "./format";

export type CardState = "pending" | "working" | "paid" | "cancelled" | "expired" | "replaced" | "failed";

/**
 * Figma "Minimalist Confirmation Card": 440px white card, yellow strip with "Confirm payment" and the countdown,
 * five rows, small Cancel (ghost) and Confirm (success) buttons. Nothing is paid until Confirm is pressed.
 */
export function ConfirmCard({
  action,
  state,
  onDecide,
}: {
  action: PendingAction;
  state: CardState;
  onDecide: (decision: "confirm" | "cancel") => void;
}) {
  const expiresAt = new Date(action.expiresAt).getTime();
  const [now, setNow] = useState(() => Date.now());
  const live = state === "pending" || state === "working";

  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [live]);

  const expired = live && now >= expiresAt;
  const shown: CardState = expired ? "expired" : state;
  const status: Record<CardState, string> = {
    pending: `Expires in ${countdown(expiresAt - now)}`,
    working: "Processing…",
    paid: "Paid",
    cancelled: "Cancelled",
    expired: "Expired",
    replaced: "Replaced",
    failed: "Not paid",
  };

  const rows: Array<[string, string, string?]> = [
    ["Student", action.studentNo, "type-label-strong"],
    ["Term", action.term, "type-label-strong"],
    ["Amount", money(action.amount, action.currency), "type-amount"],
    ["Current balance", money(action.balance, action.currency)],
    ["Balance after payment", money(action.balanceAfter, action.currency)],
  ];

  return (
    <section
      aria-label="Confirm payment"
      className={cn(
        "w-full max-w-card overflow-hidden rounded-md border border-border-light bg-bg-card text-text-on-light shadow-sm",
        !live && "opacity-90",
      )}
    >
      <header
        className={cn(
          "flex h-9 items-center justify-between px-lg",
          shown === "paid" ? "bg-accent-success text-text-on-dark" : shown === "pending" || shown === "working" ? "bg-accent-primary" : "bg-border-light",
        )}
      >
        <span className="type-label-bold">Confirm payment</span>
        <span className="type-label tabular-nums" aria-live="polite">
          {status[shown]}
        </span>
      </header>
      <div className="flex flex-col p-lg">
        {rows.map(([label, value, style]) => (
          <div key={label} className="flex items-center justify-between border-b border-border-divider py-sm">
            <span className="type-label text-text-on-light-muted">{label}</span>
            <span className={cn(style ?? "type-body-sm", "tabular-nums")}>{value}</span>
          </div>
        ))}
        {(shown === "pending" || shown === "working") && (
          <div className="flex justify-end gap-sm pt-lg">
            <Button
              variant="ghost"
              className="text-text-on-light-muted hover:bg-border-divider hover:text-text-on-light"
              disabled={shown === "working"}
              onClick={() => onDecide("cancel")}
            >
              Cancel
            </Button>
            <Button variant="success" disabled={shown === "working"} onClick={() => onDecide("confirm")}>
              Confirm
            </Button>
          </div>
        )}
        {shown === "expired" && (
          <p className="pt-lg type-caption text-text-on-light-muted">This confirmation expired. Ask the assistant to prepare the payment again.</p>
        )}
        {shown === "replaced" && <p className="pt-lg type-caption text-text-on-light-muted">A newer payment card replaced this one.</p>}
      </div>
    </section>
  );
}
