import { useState, type FormEvent } from "react";
import { addTuition, STUDENT_NO_PATTERN, TERM_PATTERN, type AddTuitionResponse } from "../../api/admin";
import { ApiError } from "../../api/client";
import { money } from "../chat/format";
import { Button, TextField } from "../ui";
import { Panel } from "./Panel";

type Field = "studentNo" | "term" | "amount" | "currency";
type Errors = Partial<Record<Field, string>>;

function validate(v: Record<Field, string>): Errors {
  const e: Errors = {};
  if (!STUDENT_NO_PATTERN.test(v.studentNo.trim())) e.studentNo = "Letters and digits only, e.g. S1004";
  if (!TERM_PATTERN.test(v.term.trim().toUpperCase())) e.term = "Use YYYY-FALL or YYYY-SPRING";
  const amount = v.amount.replace(/,/g, "").trim();
  if (!/^\d{1,10}(\.\d{1,2})?$/.test(amount) || Number(amount) <= 0) e.amount = "A positive amount with at most 2 decimals";
  if (!/^[A-Za-z]{3}$/.test(v.currency.trim())) e.currency = "3 letters, e.g. USD";
  return e;
}

/** FR-07: add a tuition record, or update its amount when the student already has one for the term. */
export function AddTuitionForm({ onSaved }: { onSaved: (result: AddTuitionResponse) => void }) {
  const [values, setValues] = useState<Record<Field, string>>({ studentNo: "", term: "2026-FALL", amount: "", currency: "USD" });
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  const set = (field: Field) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setValues((v) => ({ ...v, [field]: e.target.value }));
    setErrors((er) => ({ ...er, [field]: undefined }));
  };

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const found = validate(values);
    setErrors(found);
    setResult(null);
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      const res = await addTuition({
        studentNo: values.studentNo.trim().toUpperCase(),
        term: values.term.trim().toUpperCase(),
        amount: Number(values.amount.replace(/,/g, "")).toFixed(2),
        currency: values.currency.trim().toUpperCase(),
      });
      const amount = money(res.amount, res.currency);
      setResult({
        ok: true,
        text: res.status === "CREATED"
          ? `Created: ${res.studentNo} · ${res.term} · ${amount}`
          : `Updated: ${res.studentNo} · ${res.term} · ${money(res.previousAmount ?? "0", res.currency)} → ${amount}`,
      });
      setValues((v) => ({ ...v, studentNo: "", amount: "" }));
      onSaved(res);
    } catch (err) {
      if (err instanceof ApiError && err.code === "VALIDATION_ERROR" && Array.isArray(err.details)) {
        const fieldErrors: Errors = {};
        for (const d of err.details as Array<{ field: string; message: string }>) fieldErrors[d.field as Field] = d.message;
        setErrors(fieldErrors);
      } else {
        setResult({ ok: false, text: err instanceof ApiError ? err.message : "The tuition could not be saved." });
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Add or update tuition">
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-lg">
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-md">
          <TextField label="Student No" placeholder="S1004" value={values.studentNo} onChange={set("studentNo")} error={errors.studentNo} />
          <TextField label="Term" placeholder="2026-FALL" value={values.term} onChange={set("term")} error={errors.term} />
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)_100px] gap-md">
          <TextField label="Amount" placeholder="7,500.00" inputMode="decimal" value={values.amount} onChange={set("amount")} error={errors.amount} />
          <TextField label="Currency" placeholder="USD" maxLength={3} value={values.currency} onChange={set("currency")} error={errors.currency} />
        </div>
        <p className="type-caption text-text-placeholder">If a record already exists for this student and term, its amount is updated.</p>
        {result && (
          <p role="status" className={result.ok ? "type-label text-accent-success" : "type-label text-accent-danger"}>
            {result.text}
          </p>
        )}
        <Button type="submit" size="lg" className="w-full" disabled={busy}>
          {busy ? "Saving…" : "Save tuition"}
        </Button>
      </form>
    </Panel>
  );
}
