import { useRef, useState, type DragEvent } from "react";
import { MAX_CSV_BYTES, uploadBatch, type BatchResponse } from "../../api/admin";
import { ApiError } from "../../api/client";
import { cn } from "../ui";
import { Panel } from "./Panel";

/** FR-08: CSV upload (studentNo,term,amount,currency). Each row is processed on its own; failures are listed by line. */
export function BatchUpload({ onDone }: { onDone: (result: BatchResponse) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState<string | null>(null);
  const [result, setResult] = useState<BatchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handle(selected: File | undefined) {
    if (!selected || busy) return;
    setFile(selected.name);
    setResult(null);
    setError(null);
    if (!selected.name.toLowerCase().endsWith(".csv")) return setError("Choose a .csv file.");
    if (selected.size > MAX_CSV_BYTES) return setError("The file is larger than 1 MB.");
    setBusy(true);
    try {
      const res = await uploadBatch(selected);
      setResult(res);
      onDone(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The file could not be uploaded.");
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    void handle(e.dataTransfer.files[0]);
  };

  return (
    <Panel title="Batch upload (CSV)">
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        disabled={busy}
        aria-label="Upload a CSV file"
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-[6px] rounded-md border border-dashed px-lg py-[20px] text-center transition",
          dragging ? "border-accent-primary bg-bg-elevated" : "border-border-dark-strong hover:border-text-placeholder",
          busy && "cursor-wait opacity-70",
        )}
      >
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true" className="text-text-on-dark-muted">
          <path d="M10 13V3.5M10 3.5L6 7.5M10 3.5L14 7.5M3.5 13.5V15.5C3.5 16.05 3.95 16.5 4.5 16.5H15.5C16.05 16.5 16.5 16.05 16.5 15.5V13.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span className="type-body-sm text-text-on-dark">{busy ? "Uploading…" : "Drop a CSV file here or browse"}</span>
        <span className="type-mono text-text-on-dark-muted">studentNo,term,amount,currency</span>
      </button>
      <input ref={inputRef} type="file" accept=".csv,text/csv" className="hidden" data-testid="csv-input" onChange={(e) => void handle(e.target.files?.[0])} />

      {error && (
        <p role="alert" className="type-label text-accent-danger">
          {file ? `${file}: ` : ""}
          {error}
        </p>
      )}
      {result && (
        <div className="flex flex-col gap-[6px]" role="status">
          <div className="flex flex-wrap gap-x-md gap-y-xs type-label">
            <span className="text-text-on-dark">{file}</span>
            <span className="text-text-on-dark-muted">{result.totalRows} processed</span>
            <span className="text-accent-success">{result.successCount} succeeded</span>
            <span className={result.failureCount ? "text-accent-danger" : "text-text-on-dark-muted"}>{result.failureCount} failed</span>
          </div>
          {result.successCount > 0 && (
            <p className="type-caption text-text-on-dark-muted">
              {result.createdCount} created · {result.updatedCount} updated
            </p>
          )}
          {result.errors.length > 0 && (
            <ul className="flex max-h-48 flex-col gap-xs overflow-auto">
              {result.errors.map((e) => (
                <li key={`${e.row}-${e.code}`} className="type-caption text-text-on-dark-muted">
                  Row {e.row} · {e.reason}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Panel>
  );
}
