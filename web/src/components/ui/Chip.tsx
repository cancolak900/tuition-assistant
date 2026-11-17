import type { ButtonHTMLAttributes } from "react";
import { cn } from "./cn";

/** Figma component "Chip": suggestion chip, 30px high, radius sm, elevated background. */
export function Chip({ className, type = "button", ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex h-[30px] items-center rounded-sm border border-border-dark-strong bg-bg-elevated px-md",
        "type-caption text-text-on-dark transition hover:border-accent-primary",
        "cursor-pointer disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
