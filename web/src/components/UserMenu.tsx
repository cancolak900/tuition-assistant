import { useEffect, useRef, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { initialsOf } from "../auth/session";
import { Avatar, Button } from "./ui";

/** Avatar in the App Header; opens a small menu with the signed-in account and "Sign out". */
export function UserMenu() {
  const { user, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  if (!user) return null;
  return (
    <div ref={ref} className="relative">
      <button type="button" aria-haspopup="menu" aria-expanded={open} aria-label="Account menu" onClick={() => setOpen((o) => !o)} className="cursor-pointer rounded-full">
        <Avatar initials={initialsOf(user)} />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 mt-sm w-56 rounded-lg border border-border-dark-strong bg-bg-elevated p-md shadow-lg">
          <p className="type-label-strong text-text-on-dark">{user.studentNo ?? user.username}</p>
          <p className="mb-md type-caption text-text-on-dark-muted">
            {user.username} · {user.role}
          </p>
          <Button variant="secondary" className="w-full" role="menuitem" onClick={() => signOut()}>
            Sign out
          </Button>
        </div>
      )}
    </div>
  );
}
