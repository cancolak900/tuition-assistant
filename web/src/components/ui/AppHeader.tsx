import type { ReactNode } from "react";
import { cn } from "./cn";

/** Figma component "App Header": 56px bar, "TUITION ASSISTANT" wordmark with a yellow dot, optional right side. */
export function AppHeader({ right, wide = false }: { right?: ReactNode; wide?: boolean }) {
  return (
    <header className="sticky top-0 z-10 h-14 border-b border-border-dark bg-bg-header">
      <div className={cn("mx-auto flex h-full items-center justify-between px-xl", wide ? "max-w-[1184px]" : "max-w-chat")}>
        <div className="flex items-center gap-[6px]">
          <span className="type-wordmark tracking-wide text-text-on-dark">TUITION ASSISTANT</span>
          <span className="size-2 rounded-full bg-accent-primary" aria-hidden="true" />
        </div>
        {right && <div className="flex items-center gap-md">{right}</div>}
      </div>
    </header>
  );
}
