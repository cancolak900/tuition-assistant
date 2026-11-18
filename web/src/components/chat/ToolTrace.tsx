import { useState } from "react";
import type { TraceStep } from "../../api/agent";
import { cn } from "../ui";
import { compactJson, summarize } from "./format";

/**
 * Figma "Tool Trace Clean Collapsible": "▾ Tool trace · N steps · X ms", then one mono line per step:
 * step number (bold, info blue), tool, input, "→" result summary and duration. A line opens the full output.
 */
export function ToolTrace({ steps, defaultOpen = false }: { steps: TraceStep[]; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const [expanded, setExpanded] = useState<number | null>(null);
  if (steps.length === 0) return null;
  const total = steps.reduce((sum, s) => sum + s.durationMs, 0);

  return (
    <div className="flex flex-col gap-sm">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="cursor-pointer self-start type-caption text-text-on-dark-muted hover:text-text-on-dark"
      >
        {open ? "▾" : "▸"} Tool trace · {steps.length} {steps.length === 1 ? "step" : "steps"} · {total} ms
      </button>
      {open && (
        <ol className="flex flex-col gap-[6px] border-l border-border-dark py-xs pl-lg" aria-label="Tool trace">
          {steps.map((s) => (
            <li key={s.step} className="min-w-0">
              <button
                type="button"
                aria-expanded={expanded === s.step}
                onClick={() => setExpanded(expanded === s.step ? null : s.step)}
                className="w-full cursor-pointer text-left [overflow-wrap:anywhere] type-mono text-text-on-dark-muted hover:text-text-on-dark"
                title="Show the full result"
              >
                <span className="type-mono-bold text-accent-info">{s.step}</span>{" "}
                <span className="text-text-on-dark">{s.tool}</span>{" "}
                <span className="break-all">{compactJson(s.input)}</span> →{" "}
                <span className={cn(s.status === "error" && "text-accent-danger")}>{summarize(s)}</span>{" "}
                <span className="text-text-placeholder">
                  {s.durationMs} ms · {s.kind}
                </span>
              </button>
              {expanded === s.step && (
                <pre className="mt-xs max-h-72 overflow-auto rounded-sm border border-border-dark bg-bg-surface p-md type-mono whitespace-pre-wrap break-words text-text-on-dark-muted">
                  {JSON.stringify(s.output, null, 2)}
                </pre>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
