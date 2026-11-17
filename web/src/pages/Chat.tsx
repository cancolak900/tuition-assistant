import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useAuth } from "../auth/AuthContext";
import { ConfirmCard } from "../components/chat/ConfirmCard";
import { clock } from "../components/chat/format";
import { ToolTrace } from "../components/chat/ToolTrace";
import { useConversation, type Item } from "../components/chat/useConversation";
import { UserMenu } from "../components/UserMenu";
import { AppHeader, Chip, SendButton, cn } from "../components/ui";

/** Figma screen "Chat" (1:2): 900px column, plain assistant text, user bubbles, tool trace, confirmation card. */

const SUGGESTIONS = ["What is my balance?", "When is the Fall payment deadline?", "Installment rules", "Pay my Fall balance"];
const MAX_CHARS = 2000;

function Time({ at, align = "left" }: { at: string; align?: "left" | "right" }) {
  return <time dateTime={at} className={cn("block pt-xs type-micro text-text-placeholder", align === "right" && "pr-xs text-right")}>{clock(at)}</time>;
}

function Message({ item, onDecide }: { item: Item; onDecide: (id: string, d: "confirm" | "cancel") => void }) {
  if (item.kind === "user") {
    return (
      <div className="flex flex-col items-end">
        <div className="max-w-[80%] rounded-lg bg-bg-elevated px-lg py-md type-body-sm whitespace-pre-wrap break-words text-text-on-dark">{item.text}</div>
        <Time at={item.at} align="right" />
      </div>
    );
  }
  if (item.kind === "card") {
    return <ConfirmCard action={item.action} state={item.state} onDecide={(d) => onDecide(item.id, d)} />;
  }
  return (
    <div className="flex flex-col gap-sm">
      <div>
        <p className={cn("type-body whitespace-pre-wrap break-words", item.error ? "text-accent-danger" : "text-text-on-dark")}>{item.text}</p>
        <Time at={item.at} />
      </div>
      <ToolTrace steps={item.trace} />
    </div>
  );
}

function Thinking() {
  return (
    <div className="flex items-center gap-sm type-body-sm text-text-on-dark-muted" role="status">
      <span className="flex gap-[3px]" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <span key={i} className="size-1.5 animate-pulse rounded-full bg-accent-primary" style={{ animationDelay: `${i * 150}ms` }} />
        ))}
      </span>
      Thinking…
    </div>
  );
}

export function Chat() {
  const { user } = useAuth();
  const { items, busy, send, decide, openCard } = useConversation(String(user?.userId ?? "anon"));
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const atBottom = useRef(true);

  // Remember whether the reader is at the end of the conversation (measured before new content arrives).
  useEffect(() => {
    const update = () => {
      const doc = document.documentElement;
      atBottom.current = window.innerHeight + window.scrollY >= doc.scrollHeight - 120;
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, []);

  // Follow the conversation: always after the student's own message, otherwise only if they were already at
  // the end (someone reading an older answer is not pulled down). Scrolling to the very bottom of the page
  // keeps the last message above the sticky input bar, which used to cover it.
  const last = items[items.length - 1];
  useEffect(() => {
    if (!last || !(atBottom.current || last.kind === "user")) return;
    const frame = window.requestAnimationFrame(() => {
      window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" });
      atBottom.current = true;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [items.length, busy, last]);

  const submit = (text: string) => {
    if (busy || !text.trim()) return;
    setDraft("");
    void send(text);
    inputRef.current?.focus();
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit(draft);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit(draft);
    }
  };

  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader right={<UserMenu />} />

      <main className="mx-auto flex w-full max-w-chat flex-1 flex-col px-xl pt-2xl pb-xl">
        {items.length === 0 ? (
          <div className="flex flex-1 flex-col justify-center gap-sm pb-[10vh]">
            <h1 className="type-display">How can I help{user?.studentNo ? `, ${user.studentNo}` : ""}?</h1>
            <p className="type-body text-text-on-dark-muted">
              Ask about deadlines, installments or your balance. Payments are only made after you confirm them.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-xl" aria-live="polite">
            {items.map((item) => (
              <Message key={item.id} item={item} onDecide={decide} />
            ))}
            {busy && <Thinking />}
          </div>
        )}
      </main>

      <div className="sticky bottom-0 bg-gradient-to-t from-bg-page from-70% to-transparent pt-lg pb-xl">
        <form onSubmit={onSubmit} className="mx-auto flex w-full max-w-chat flex-col gap-xs px-xl">
          <div className="flex flex-wrap gap-sm pb-xs">
            {openCard && (
              <Chip onClick={() => decide(openCard.id, "cancel")} disabled={busy}>
                Cancel payment
              </Chip>
            )}
            {SUGGESTIONS.map((s) => (
              <Chip key={s} onClick={() => submit(s)} disabled={busy}>
                {s}
              </Chip>
            ))}
          </div>
          <div className="flex items-end gap-md rounded-lg border border-border-dark bg-bg-surface py-sm pr-sm pl-[20px] focus-within:border-border-dark-strong">
            <textarea
              ref={inputRef}
              aria-label="Message"
              rows={1}
              maxLength={MAX_CHARS}
              placeholder="Ask about your tuition…"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              autoFocus
              className="max-h-40 min-h-8 flex-1 resize-none bg-transparent py-[6px] type-body-sm text-text-on-dark outline-none placeholder:text-text-placeholder field-sizing-content"
            />
            <SendButton disabled={busy || !draft.trim()} />
          </div>
          <p className="px-xs type-micro text-text-placeholder">The assistant answers from the university policy and your own records. Check payments on the card before confirming.</p>
        </form>
      </div>
    </div>
  );
}
