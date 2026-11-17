import { cn } from "./cn";

/** Figma component "Avatar": 32px circle with initials (Micro). */
export function Avatar({ initials, className, title }: { initials: string; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex size-8 shrink-0 select-none items-center justify-center rounded-full",
        "border border-border-dark-strong bg-bg-elevated type-micro text-text-on-dark",
        className,
      )}
    >
      {initials}
    </span>
  );
}
