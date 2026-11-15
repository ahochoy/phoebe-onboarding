import { useQueryClient } from "@tanstack/react-query";
import { Dialog } from "radix-ui";
import { useState, type FormEvent } from "react";
import { ApiError, apiSend, apiUpload } from "../api/client";
import type { LinkBody } from "../api/types";
import { messageFor } from "../lib/messages";
import { useStatus } from "../state/status";
import { Field, dialogContent, inputClass, primaryButton, secondaryButton } from "./formParts";
import { GroupSelect } from "./GroupSelect";

export const ACCEPT = ".pdf,.md,.markdown,.csv";
export const MAX_BYTES = 5 * 1024 * 1024;
export const TOO_BIG = "Files must be 5 MB or smaller.";

export type AddMode = "file" | "link";

interface FormProps {
  onDone: () => void;
  /** Called with a failed request's error; refreshes the status pill if a limit was hit. */
  onLimit: (err: unknown) => void;
}

function SubmitRow({
  busy,
  label,
  onCancel,
}: {
  busy: boolean;
  label: string;
  onCancel: () => void;
}) {
  return (
    <div className="flex justify-end gap-2 pt-2">
      <button type="button" disabled={busy} className={secondaryButton} onClick={onCancel}>
        Cancel
      </button>
      <button type="submit" disabled={busy} className={primaryButton}>
        {busy ? "Working…" : label}
      </button>
    </div>
  );
}

function UploadForm({ onDone, onLimit }: FormProps) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [groupId, setGroupId] = useState("");
  const [purpose, setPurpose] = useState("");
  const [lastUpdated, setLastUpdated] = useState("");
  const [errors, setErrors] = useState<{ file?: string; title?: string; group?: string }>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function pick(next: File | null) {
    setFile(next);
    setErrors((e) => ({
      ...e,
      file: next && next.size > MAX_BYTES ? TOO_BIG : undefined,
    }));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const next: typeof errors = {};
    if (!file) next.file = "Choose a file.";
    else if (file.size > MAX_BYTES) next.file = TOO_BIG;
    if (!title.trim()) next.title = "Enter a title.";
    if (!groupId) next.group = "Choose a group.";
    setErrors(next);
    setServerError(null);
    if (!file || Object.keys(next).length > 0) return;

    const form = new FormData();
    form.append("file", file, file.name);
    form.append("title", title.trim());
    form.append("group_id", groupId);
    form.append("purpose", purpose.trim());
    form.append("last_updated", lastUpdated);
    setBusy(true);
    try {
      await apiUpload("/api/documents/upload", form);
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      onDone();
    } catch (err) {
      onLimit(err);
      setServerError(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} noValidate className="mt-4 space-y-4">
      <Field label="File" hint="PDF, Markdown or CSV, up to 5 MB." error={errors.file}>
        {(p) => (
          <input
            {...p}
            type="file"
            accept={ACCEPT}
            className={inputClass}
            onChange={(e) => pick(e.target.files?.[0] ?? null)}
          />
        )}
      </Field>
      <Field label="Title" error={errors.title}>
        {(p) => (
          <input
            {...p}
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className={inputClass}
          />
        )}
      </Field>
      <Field label="Group" error={errors.group}>
        {(p) => <GroupSelect {...p} value={groupId} onChange={setGroupId} />}
      </Field>
      <Field label="Purpose" optional>
        {(p) => (
          <textarea
            {...p}
            rows={2}
            value={purpose}
            onChange={(e) => setPurpose(e.target.value)}
            className={inputClass}
          />
        )}
      </Field>
      <Field label="Last updated" optional>
        {(p) => (
          <input
            {...p}
            type="date"
            value={lastUpdated}
            onChange={(e) => setLastUpdated(e.target.value)}
            className={inputClass}
          />
        )}
      </Field>
      {serverError ? (
        <p role="alert" className="text-sm font-medium text-danger">
          {serverError}
        </p>
      ) : null}
      <SubmitRow busy={busy} label="Upload" onCancel={onDone} />
    </form>
  );
}

function LinkForm({ onDone, onLimit }: FormProps) {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [groupId, setGroupId] = useState("");
  const [purpose, setPurpose] = useState("");
  const [lastUpdated, setLastUpdated] = useState("");
  const [errors, setErrors] = useState<{ url?: string; title?: string; group?: string }>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const next: typeof errors = {};
    if (!url.trim()) next.url = "Enter a link address.";
    if (!title.trim()) next.title = "Enter a title.";
    if (!groupId) next.group = "Choose a group.";
    setErrors(next);
    setServerError(null);
    if (Object.keys(next).length > 0) return;

    const body: LinkBody = {
      url: url.trim(),
      title: title.trim(),
      purpose: purpose.trim(),
      group_id: groupId,
      ...(lastUpdated ? { last_updated: lastUpdated } : {}),
    };
    setBusy(true);
    try {
      await apiSend("POST", "/api/documents/link", body);
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      onDone();
    } catch (err) {
      onLimit(err);
      setServerError(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} noValidate className="mt-4 space-y-4">
      <Field label="Link address" error={errors.url}>
        {(p) => (
          <input
            {...p}
            type="url"
            inputMode="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className={inputClass}
          />
        )}
      </Field>
      <Field label="Title" error={errors.title}>
        {(p) => (
          <input
            {...p}
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className={inputClass}
          />
        )}
      </Field>
      <Field label="Group" error={errors.group}>
        {(p) => <GroupSelect {...p} value={groupId} onChange={setGroupId} />}
      </Field>
      <Field label="Purpose" optional>
        {(p) => (
          <textarea
            {...p}
            rows={2}
            value={purpose}
            onChange={(e) => setPurpose(e.target.value)}
            className={inputClass}
          />
        )}
      </Field>
      <Field label="Last updated" optional>
        {(p) => (
          <input
            {...p}
            type="date"
            value={lastUpdated}
            onChange={(e) => setLastUpdated(e.target.value)}
            className={inputClass}
          />
        )}
      </Field>
      {serverError ? (
        <p role="alert" className="text-sm font-medium text-danger">
          {serverError}
        </p>
      ) : null}
      <SubmitRow busy={busy} label="Add link" onCancel={onDone} />
    </form>
  );
}

/** Upload-a-file and add-a-link dialog. The form mounts only while open, so it resets each time. */
export function AddDocumentDialog({
  mode,
  onClose,
}: {
  mode: AddMode | null;
  onClose: () => void;
}) {
  const { refresh } = useStatus();
  const onLimit = (err: unknown) => {
    if (err instanceof ApiError && (err.status === 429 || err.status === 503)) refresh();
  };
  return (
    <Dialog.Root open={mode !== null} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/40" />
        <Dialog.Content className={dialogContent}>
          <Dialog.Title className="text-lg font-semibold">
            {mode === "link" ? "Add a link" : "Upload a document"}
          </Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-ink/80">
            {mode === "link"
              ? "Phoebe reads the page and answers from it."
              : "Phoebe reads the file and answers from it."}
          </Dialog.Description>
          {mode === "link" ? <LinkForm onDone={onClose} onLimit={onLimit} /> : null}
          {mode === "file" ? <UploadForm onDone={onClose} onLimit={onLimit} /> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
