import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { fetchMe, login as apiLogin, type Me } from "../api/auth";
import { configureClient } from "../api/client";
import { clearSession, loadSession, saveSession, tokenExpiry, type Session } from "./session";

interface AuthState {
  user: Me | null;
  token: string | null;
  /** Set when the user was signed out because the token expired or was rejected. */
  notice: string | null;
  signIn: (username: string, password: string) => Promise<Me>;
  signOut: (notice?: string) => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => loadSession());
  const [notice, setNotice] = useState<string | null>(null);

  const signOut = useCallback((message?: string) => {
    clearSession();
    configureClient(null);
    setSession(null);
    setNotice(message ?? null);
  }, []);

  // Keep the API client in sync, and sign out when the gateway rejects the token (401).
  configureClient(session?.token ?? null, () => signOut("Your session has expired. Please sign in again."));

  // Sign out exactly when the token expires.
  useEffect(() => {
    if (!session) return;
    const ms = session.expiresAt - Date.now();
    const timer = window.setTimeout(() => signOut("Your session has expired. Please sign in again."), Math.max(ms, 0));
    return () => window.clearTimeout(timer);
  }, [session, signOut]);

  const signIn = useCallback(async (username: string, password: string) => {
    const tokens = await apiLogin(username, password);
    configureClient(tokens.accessToken);
    const user = await fetchMe(); // verified by Kong's JWT plugin and the API
    const next: Session = {
      token: tokens.accessToken,
      user,
      expiresAt: tokenExpiry(tokens.accessToken) ?? Date.now() + tokens.expiresIn * 1000,
    };
    saveSession(next);
    setNotice(null);
    setSession(next);
    return user;
  }, []);

  const value = useMemo<AuthState>(
    () => ({ user: session?.user ?? null, token: session?.token ?? null, notice, signIn, signOut }),
    [session, notice, signIn, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
