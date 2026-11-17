import type { Me } from "../api/auth";

/**
 * The JWT is kept in sessionStorage: it survives a page reload but not closing the tab, and it is never
 * written to localStorage or cookies. The expiry comes from the token's own `exp` claim.
 */

const KEY = "tuition-assistant.session";

export interface Session {
  token: string;
  user: Me;
  expiresAt: number; // epoch ms
}

export function tokenExpiry(token: string): number | null {
  try {
    const payload = token.split(".")[1];
    const json = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    return typeof json.exp === "number" ? json.exp * 1000 : null;
  } catch {
    return null;
  }
}

export function saveSession(session: Session): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(session));
  } catch {
    // storage blocked (private mode): the session then lives only in memory
  }
}

export function loadSession(now = Date.now()): Session | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const session = JSON.parse(raw) as Session;
    if (!session.token || !session.user || session.expiresAt <= now) {
      sessionStorage.removeItem(KEY);
      return null;
    }
    return session;
  } catch {
    return null;
  }
}

export function clearSession(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // ignore
  }
}

/** Where each role lands after signing in. */
export function homeFor(role: Me["role"]): string {
  return role === "admin" ? "/admin" : role === "student" ? "/chat" : "/account";
}

export function initialsOf(user: Me): string {
  const source = user.studentNo ?? user.username;
  return source.slice(0, 2).toUpperCase();
}
