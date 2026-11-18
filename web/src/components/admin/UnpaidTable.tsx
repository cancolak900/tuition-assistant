import { useEffect, useState } from "react";
import { listUnpaid, TERM_PATTERN, type UnpaidItem, type UnpaidPage } from "../../api/admin";
import { ApiError } from "../../api/client";
import { money } from "../chat/format";
import { Button, Table, type Column } from "../ui";
import { Panel } from "./Panel";

const PAGE_SIZE = 10;
const PHONE = "(max-width: 639px)";

/** True on phone-width screens; follows rotation and window resizes. */
function usePhone(): boolean {
  const query = () => typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(PHONE).matches;
  const [phone, setPhone] = useState(query);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mql = window.matchMedia(PHONE);
    const onChange = () => setPhone(mql.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);
  return phone;
}

/** Phone layout: one compact row per student instead of a six-column table that would need side scrolling. */
function UnpaidList({ rows, empty }: { rows: UnpaidItem[]; empty: string }) {
  if (rows.length === 0) return <p className="py-xl text-center type-body-sm text-text-on-dark-muted">{empty}</p>;
  return (
    <ul className="flex flex-col" aria-label="Unpaid tuition">
      {rows.map((r) => (
        <li key={r.studentNo} className="flex items-center justify-between gap-md border-b border-border-dark py-md">
          <div className="min-w-0">
            <p className="type-label-strong text-text-on-dark">
              {r.studentNo} <span className="font-normal text-text-on-dark-muted">· {r.fullName}</span>
            </p>
            <p className="type-caption text-text-on-dark-muted">
              Paid {money(r.paid, r.currency)} of {money(r.tuitionTotal, r.currency)}
            </p>
          </div>
          <span className="shrink-0 type-label-strong tabular-nums text-accent-primary">{money(r.balance, r.currency)}</span>
        </li>
      ))}
    </ul>
  );
}

/** FR-09: paged list of students with a remaining balance for one term. */
export function UnpaidTable({ refreshKey }: { refreshKey: number }) {
  const [termInput, setTermInput] = useState("2026-FALL");
  const [term, setTerm] = useState("2026-FALL");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<UnpaidPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const phone = usePhone();

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    listUnpaid(term, page, PAGE_SIZE, controller.signal)
      .then((res) => {
        setData(res);
        if (res.totalPages > 0 && page > res.totalPages) setPage(res.totalPages);
      })
      .catch((err) => {
        if ((err as Error).name === "AbortError") return;
        setError(err instanceof ApiError ? err.message : "The list could not be loaded.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [term, page, refreshKey]);

  const applyTerm = () => {
    const next = termInput.trim().toUpperCase();
    setTermInput(next);
    if (TERM_PATTERN.test(next) && next !== term) {
      setTerm(next);
      setPage(1);
    }
  };
  const termInvalid = termInput.trim() !== "" && !TERM_PATTERN.test(termInput.trim().toUpperCase());

  const columns: Column<UnpaidItem>[] = [
    { key: "student", header: "Student", render: (r) => r.studentNo },
    { key: "name", header: "Name", render: (r) => r.fullName, muted: true },
    { key: "term", header: "Term", render: () => data?.term ?? term, muted: true },
    { key: "tuition", header: "Tuition", render: (r) => money(r.tuitionTotal, r.currency) },
    { key: "paid", header: "Paid", render: (r) => money(r.paid, r.currency) },
    { key: "balance", header: "Balance", render: (r) => money(r.balance, r.currency), emphasis: true },
  ];

  const total = data?.totalItems ?? 0;
  const first = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const last = Math.min(page * PAGE_SIZE, total);
  const pages = Math.max(data?.totalPages ?? 1, 1);

  return (
    <Panel
      title="Unpaid tuition"
      subtitle="Students with a remaining balance"
      className="min-w-0 flex-1"
      actions={
        <label className="flex items-center gap-sm">
          <span className="type-caption text-text-on-dark-muted">Term</span>
          <input
            aria-label="Term"
            aria-invalid={termInvalid || undefined}
            value={termInput}
            onChange={(e) => setTermInput(e.target.value)}
            onBlur={applyTerm}
            onKeyDown={(e) => e.key === "Enter" && applyTerm()}
            placeholder="2026-FALL"
            className={`h-11 w-32 rounded-lg sm:w-40 border bg-bg-surface px-lg type-body-sm text-text-on-dark outline-none placeholder:text-text-placeholder ${termInvalid ? "border-accent-danger" : "border-border-dark focus:border-accent-primary"}`}
          />
        </label>
      }
    >
      {error ? (
        <p role="alert" className="type-body-sm text-accent-danger">{error}</p>
      ) : (
        <div className={loading ? "overflow-x-auto opacity-60 transition" : "overflow-x-auto transition"} aria-busy={loading}>
          {phone ? (
            <UnpaidList rows={data?.items ?? []} empty={loading ? "Loading…" : `No unpaid tuition for ${term}.`} />
          ) : (
            <Table columns={columns} rows={data?.items ?? []} rowKey={(r) => r.studentNo} empty={loading ? "Loading…" : `No unpaid tuition for ${term}.`} />
          )}
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-md">
        <span className="type-caption text-text-on-dark-muted">
          Showing {first}–{last} of {total}
        </span>
        <div className="flex items-center gap-sm">
          <Button variant="secondary" disabled={loading || page <= 1} onClick={() => setPage((p) => p - 1)}>
            {phone ? "Prev" : "Previous"}
          </Button>
          <span className="type-caption text-text-on-dark-muted">
            Page {Math.min(page, pages)} of {pages}
          </span>
          <Button variant="secondary" disabled={loading || page >= pages} onClick={() => setPage((p) => p + 1)}>
            Next
          </Button>
        </div>
      </div>
    </Panel>
  );
}
