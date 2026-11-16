import { useQueryClient } from "@tanstack/react-query";
import { Dialog } from "radix-ui";
import { useState, type FormEvent } from "react";
import { apiSend } from "../api/client";
import type { DocumentOut, DocumentPatch } from "../api/types";
import { messageFor } from "../lib/messages";
import { Field, dialogContent, inputClass, primaryButton, secondaryButton } from "./formParts";
import { GroupSelect } from "./GroupSelect";

function EditForm({ doc, onDone }: { doc: DocumentOut; onDone: () => void }) {
  const queryClient = useQueryClient();
  const original = {
    title: doc.title,
    purpose: doc.purpose,
    lastUpdated: doc.last_updated?.slice(0, 10) ?? "",
    groupId: doc.group_id,
  };
  const [title, setTitle] = useState(original.title);
  const [purpose, setPurpose] = useState(original.purpose);
  const [lastUpdated, setLastUpdated] = useState(original.lastUpdated);
  const [groupId, setGroupId] = useState(original.groupId);
  const [titleError, setTitleError] = useState<string | undefined>();
  const [serverError, setServerError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setServerError(null);
    if (!title.trim()) {
      setTitleError("Enter a title.");
      return;
    }
    setTitleError(undefined);

    // Only changed fields. An emptied date is an explicit null (clear it); title and
    // group_id are never null.
    const patch: DocumentPatch = {};
    if (title.trim() !== original.title) patch.title = title.trim();
    if (purpose.trim() !== original.purpose) patch.purpose = purpose.trim();
    if (lastUpdated !== original.lastUpdated) patch.last_updated = lastUpdated || null;
    if (groupId !== original.groupId) patch.group_id = groupId;
    if (Object.keys(patch).length === 0) {
      onDone();
      return;
    }

    setBusy(true);
    try {
      await apiSend("PATCH", `/api/documents/${encodeURIComponent(doc.id)}`, patch);
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      await queryClient.invalidateQueries({ queryKey: ["document", doc.id] });
      onDone();
    } catch (err) {
      setServerError(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} noValidate className="mt-4 space-y-4">
      <Field label="Title" error={titleError}>
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
      <Field label="Group">
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
      <div className="flex justify-end gap-2 pt-2">
        <button type="button" disabled={busy} className={secondaryButton} onClick={onDone}>
          Cancel
        </button>
        <button type="submit" disabled={busy} className={primaryButton}>
          {busy ? "Saving…" : "Save"}
        </button>
      </div>
    </form>
  );
}

/** Edit a document's title, group, purpose and last-updated date. */
export function EditDocumentDialog({
  doc,
  onClose,
}: {
  doc: DocumentOut | null;
  onClose: () => void;
}) {
  return (
    <Dialog.Root open={doc !== null} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/40" />
        <Dialog.Content className={dialogContent}>
          <Dialog.Title className="text-lg font-semibold">Edit document</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-ink/80">
            Update how this document is described and where it is shared.
          </Dialog.Description>
          {doc ? <EditForm key={doc.id} doc={doc} onDone={onClose} /> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
