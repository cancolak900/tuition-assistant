import type { ReactNode } from "react";

/**
 * Figma component "App Header": 56px full-width bar. The "TUITION ASSISTANT" wordmark (with the yellow dot) sits
 * at the left edge and the right-hand content (avatar menu) at the right edge, 24px from the window sides,
 * while each screen keeps its own centred content column.
 */
export function AppHeader({ right }: { right?: ReactNode }) {
  return (
    <header className="sticky top-0 z-10 h-14 border-b border-border-dark bg-bg-header">
      <div className="flex h-full items-center justify-between px-xl">
        <div className="flex items-center gap-[6px]">
          <span className="type-wordmark tracking-wide text-text-on-dark">TUITION ASSISTANT</span>
          <span className="size-2 rounded-full bg-accent-primary" aria-hidden="true" />
        </div>
        {right && <div className="flex items-center gap-md">{right}</div>}
      </div>
    </header>
  );
}
