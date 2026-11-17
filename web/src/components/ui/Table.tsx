import type { ReactNode } from "react";
import { cn } from "./cn";

/** Figma component "Table Row": Header (36px, strong divider, upper-case caption) and Row (44px, Body/Small). */
export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  align?: "left" | "right";
  emphasis?: boolean; // Label/SemiBold, used for the balance column
  muted?: boolean;
}

interface TableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  empty?: ReactNode;
}

export function Table<T>({ columns, rows, rowKey, empty }: TableProps<T>) {
  return (
    <table className="w-full border-collapse">
      <thead>
        <tr className="h-9 border-b border-border-dark-strong">
          {columns.map((c) => (
            <th
              key={c.key}
              scope="col"
              className={cn("px-lg type-table-head font-normal text-text-on-dark-muted", c.align === "right" ? "text-right" : "text-left")}
            >
              {c.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 && empty ? (
          <tr>
            <td colSpan={columns.length} className="px-lg py-xl text-center type-body-sm text-text-on-dark-muted">
              {empty}
            </td>
          </tr>
        ) : (
          rows.map((row) => (
            <tr key={rowKey(row)} className="h-11 border-b border-border-dark">
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={cn(
                    "px-lg",
                    c.emphasis ? "type-label-strong" : "type-body-sm",
                    c.muted ? "text-text-on-dark-muted" : "text-text-on-dark",
                    c.align === "right" ? "text-right tabular-nums" : "text-left",
                  )}
                >
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}
