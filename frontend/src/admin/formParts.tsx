import { useId, type ReactNode } from "react";

export const inputClass =
  "min-h-10 w-full rounded-md border border-ink/30 bg-white px-3 py-2 text-sm aria-[invalid=true]:border-danger";

export const buttonClass =
  "inline-flex min-h-8 cursor-pointer items-center justify-center gap-1.5 rounded-md px-3 py-1 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-60";

export const primaryButton = `${buttonClass} bg-accent text-white`;
export const secondaryButton = `${buttonClass} border border-ink/30`;

export const dialogContent =
  "fixed top-1/2 left-1/2 z-50 max-h-[calc(100dvh-2rem)] w-[min(32rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg bg-white p-6 shadow-xl";

export interface FieldControlProps {
  id: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean;
}

/** A labelled field; the error (if any) is tied to the control with aria-describedby. */
export function Field({
  label,
  optional,
  hint,
  error,
  children,
}: {
  label: string;
  optional?: boolean;
  hint?: string;
  error?: string | undefined;
  children: (props: FieldControlProps) => ReactNode;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ");
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
        {optional ? <span className="font-normal text-ink/80"> (optional)</span> : null}
      </label>
      {children({
        id,
        ...(describedBy ? { "aria-describedby": describedBy } : {}),
        ...(error ? { "aria-invalid": true } : {}),
      })}
      {hint ? (
        <p id={hintId} className="text-xs text-ink/80">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="text-sm text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
