import type { ButtonHTMLAttributes } from "react";
import { cn } from "./cn";

/** Figma component "Send Button": 32px yellow square (radius sm) with an arrow-up icon. */
export function SendButton({ className, type = "submit", ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type={type}
      aria-label={props["aria-label"] ?? "Send"}
      className={cn(
        "inline-flex size-8 shrink-0 items-center justify-center rounded-sm bg-accent-primary text-text-on-accent",
        "cursor-pointer transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-40",
        className,
      )}
      {...props}
    >
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path d="M8 12.5V3.5M8 3.5L3.5 8M8 3.5L12.5 8" stroke="currentColor" strokeWidth="1.67" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  );
}
