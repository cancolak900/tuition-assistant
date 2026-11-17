import { useId, type InputHTMLAttributes } from "react";
import { cn } from "./cn";

/** Figma component "Text Field": label (Caption), 44px field (radius lg), states Default / Focus / Error. */
export interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
}

export function TextField({ label, error, className, id, ...props }: TextFieldProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  return (
    <div className={cn("flex flex-col gap-[6px]", className)}>
      <label htmlFor={inputId} className="type-caption text-text-on-dark-muted">
        {label}
      </label>
      <input
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${inputId}-error` : undefined}
        className={cn(
          "h-11 rounded-lg border bg-bg-surface px-lg type-body-sm text-text-on-dark outline-none transition",
          "placeholder:text-text-placeholder",
          error ? "border-accent-danger" : "border-border-dark focus:border-accent-primary",
        )}
        {...props}
      />
      {error && (
        <p id={`${inputId}-error`} className="type-caption text-accent-danger">
          {error}
        </p>
      )}
    </div>
  );
}
