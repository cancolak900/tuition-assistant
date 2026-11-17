import type { ReactNode } from "react";
import { cn } from "../ui";

/** Card used by the admin screen (Figma: surface background, dark border, radius lg, 24px padding). */
export function Panel({ title, subtitle, actions, children, className }: { title: string; subtitle?: string; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section aria-label={title} className={cn("flex flex-col gap-lg rounded-lg border border-border-dark bg-bg-surface p-xl", className)}>
      <div className="flex flex-wrap items-end justify-between gap-md">
        <div className="flex flex-col gap-[2px]">
          <h2 className="type-label-strong text-text-on-dark">{title}</h2>
          {subtitle && <p className="type-caption text-text-on-dark-muted">{subtitle}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}
