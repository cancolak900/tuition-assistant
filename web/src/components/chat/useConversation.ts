import { useCallback, useEffect, useRef, useState } from "react";
import { decide as apiDecide, sendMessage, type PendingAction, type TraceStep } from "../../api/agent";
import { ApiError } from "../../api/client";
import type { CardState } from "./ConfirmCard";

export type Item =
  | { kind: "user"; id: string; text: string; at: string }
  | { kind: "assistant"; id: string; text: string; at: string; trace: TraceStep[]; error?: boolean }
  | { kind: "card"; id: string; action: PendingAction; state: CardState; at: string };

interface Stored {
  sessionId: string | null;
  items: Item[];
}

export const CHAT_STORAGE_PREFIX = "tuition-assistant.chat.";
const uid = () => Math.random().toString(36).slice(2, 10);
const now = () => new Date().toISOString();

function load(key: string): Stored {
  try {
    const raw = sessionStorage.getItem(key);
    if (raw) {
      const stored = JSON.parse(raw) as Stored;
      // A card left "working" by a reload is shown as pending again; its expiry still applies.
      stored.items = stored.items.map((i) => (i.kind === "card" && i.state === "working" ? { ...i, state: "pending" } : i));
      return stored;
    }
  } catch {
    // ignore unreadable state
  }
  return { sessionId: null, items: [] };
}

function friendly(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "LLM_BUSY") return "The assistant is busy right now. Please try again in a minute.";
    if (error.code === "AGENT_TIMEOUT") return "The assistant took too long to answer. Please try again.";
    if (error.code === "RATE_LIMITED") return "Too many messages in a short time. Please wait a moment.";
    return error.message;
  }
  return "Something went wrong. Please try again.";
}

/**
 * Chat state: messages, the agent session id and payment cards. Kept in sessionStorage per user so a reload
 * keeps the conversation (the agent session itself expires after 30 idle minutes; a new one is started then).
 */
export function useConversation(userKey: string) {
  const storageKey = CHAT_STORAGE_PREFIX + userKey;
  const [state, setState] = useState<Stored>(() => load(storageKey));
  const [busy, setBusy] = useState(false);
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(state));
    } catch {
      // storage blocked: keep the conversation in memory only
    }
  }, [state, storageKey]);

  const append = (...items: Item[]) => setState((s) => ({ ...s, items: [...s.items, ...items] }));
  const setCard = (id: string, cardState: CardState) =>
    setState((s) => ({ ...s, items: s.items.map((i) => (i.kind === "card" && i.id === id ? { ...i, state: cardState } : i)) }));

  const send = useCallback(async (text: string) => {
    const message = text.trim();
    if (!message) return;
    append({ kind: "user", id: uid(), text: message, at: now() });
    setBusy(true);
    try {
      let res;
      try {
        res = await sendMessage(message, stateRef.current.sessionId);
      } catch (e) {
        // The agent forgot the session (idle timeout or restart): start a new one and send again.
        if (e instanceof ApiError && e.code === "SESSION_NOT_FOUND") res = await sendMessage(message, null);
        else throw e;
      }
      const reply: Item = { kind: "assistant", id: uid(), text: res.reply, at: now(), trace: res.trace };
      const card: Item[] = res.pendingAction ? [{ kind: "card", id: uid(), action: res.pendingAction, state: "pending", at: now() }] : [];
      setState((s) => ({
        sessionId: res.sessionId,
        // The agent keeps one pending payment per session: an older open card no longer works.
        items: [
          ...s.items.map((i) => (card.length && i.kind === "card" && i.state === "pending" ? { ...i, state: "replaced" as const } : i)),
          reply,
          ...card,
        ],
      }));
    } catch (e) {
      append({ kind: "assistant", id: uid(), text: friendly(e), at: now(), trace: [], error: true });
    } finally {
      setBusy(false);
    }
  }, []);

  const decide = useCallback(async (cardId: string, decision: "confirm" | "cancel") => {
    const { sessionId, items } = stateRef.current;
    const card = items.find((i): i is Extract<Item, { kind: "card" }> => i.kind === "card" && i.id === cardId);
    if (!card || !sessionId) return;
    setCard(cardId, "working");
    try {
      const res = await apiDecide(sessionId, card.action.actionId, decision);
      const next: CardState = res.payment ? "paid" : res.pendingAction ? "pending" : decision === "cancel" ? "cancelled" : "failed";
      setCard(cardId, next);
      append({ kind: "assistant", id: uid(), text: res.reply, at: now(), trace: res.trace, error: next === "failed" });
    } catch (e) {
      if (e instanceof ApiError && e.code === "ACTION_EXPIRED") setCard(cardId, "expired");
      else if (e instanceof ApiError && (e.code === "ACTION_NOT_FOUND" || e.code === "SESSION_NOT_FOUND")) setCard(cardId, "expired");
      else setCard(cardId, "pending");
      append({ kind: "assistant", id: uid(), text: friendly(e), at: now(), trace: [], error: true });
    }
  }, []);

  const openCard = state.items.find((i): i is Extract<Item, { kind: "card" }> => i.kind === "card" && i.state === "pending");
  return { items: state.items, busy, send, decide, openCard };
}
