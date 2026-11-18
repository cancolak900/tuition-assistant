import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { homeFor } from "../auth/session";
import { AppHeader, Button, TextField } from "../components/ui";

/** Figma screen "Login" (5:44): 360px sign-in form, Primary/Large button, demo accounts box. */

const DEMO = { student: ["s1001", "s1002", "s1003"], bank: ["bank"], admin: ["admin"] };

function messageFor(error: unknown): { field?: string; form?: string } {
  if (error instanceof ApiError) {
    if (error.code === "INVALID_CREDENTIALS") return { field: "Invalid username or password" };
    if (error.code === "RATE_LIMITED") return { form: "Too many sign-in attempts. Wait a minute and try again." };
    if (error.code === "VALIDATION_ERROR") return { field: "Enter your username and password" };
    return { form: error.message };
  }
  return { form: "Something went wrong. Please try again." };
}

export function Login() {
  const { user, signIn, notice } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ field?: string; form?: string }>({});

  if (user) return <Navigate to={homeFor(user.role)} replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError({ field: "Enter your username and password" });
      return;
    }
    setBusy(true);
    setError({});
    try {
      const me = await signIn(username.trim(), password);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from !== "/login" ? from : homeFor(me.role), { replace: true });
    } catch (err) {
      setError(messageFor(err));
      setBusy(false);
    }
  }

  const pick = (name: string) => {
    setUsername(name);
    setError({});
    document.getElementById("password")?.focus();
  };

  return (
    <div className="flex min-h-dvh flex-col">
      <AppHeader />
      <main className="flex flex-1 items-start justify-center px-lg sm:px-xl pt-[clamp(48px,20vh,204px)] pb-2xl">
        <form onSubmit={onSubmit} noValidate className="flex w-full max-w-form flex-col gap-xl" aria-labelledby="signin-title">
          <div className="flex flex-col gap-sm">
            <h1 id="signin-title" className="type-display">Sign in</h1>
            <p className="type-body-sm text-text-on-dark-muted">
              Check your tuition balance, ask about payment rules and pay securely with your student account.
            </p>
          </div>

          {(notice || error.form) && (
            <p role="alert" className="rounded-lg border border-border-dark-strong bg-bg-surface px-lg py-md type-body-sm text-text-on-dark">
              {error.form ?? notice}
            </p>
          )}

          <div className="flex flex-col gap-lg">
            <TextField
              id="username"
              label="Username"
              placeholder="e.g. s1001"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              invalid={Boolean(error.field)}
            />
            <TextField
              id="password"
              label="Password"
              type="password"
              placeholder="••••••••"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              error={error.field}
            />
          </div>

          <Button type="submit" size="lg" className="w-full" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>

          <div className="flex flex-col gap-xs rounded-lg border border-border-dark bg-bg-surface px-lg py-md">
            <span className="type-label-strong">Demo accounts</span>
            <p className="flex flex-wrap gap-x-lg gap-y-xs type-caption text-text-on-dark-muted">
              {Object.entries(DEMO).map(([role, names]) => (
                <span key={role}>
                  {role[0].toUpperCase() + role.slice(1)}:{" "}
                  {names.map((n, i) => (
                    <span key={n}>
                      {i > 0 && " · "}
                      <button type="button" onClick={() => pick(n)} className="cursor-pointer text-text-on-dark-muted underline-offset-2 hover:text-text-on-dark hover:underline">
                        {n}
                      </button>
                    </span>
                  ))}
                </span>
              ))}
            </p>
          </div>
        </form>
      </main>
    </div>
  );
}
