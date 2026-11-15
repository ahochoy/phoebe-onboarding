import { useQueryClient } from "@tanstack/react-query";
import { Dialog } from "radix-ui";
import { useState, type FormEvent } from "react";
import { apiSend } from "../api/client";
import type { GroupNode, NewGroup } from "../api/types";
import { messageFor } from "../lib/messages";
import { Field, dialogContent, inputClass, primaryButton, secondaryButton } from "./formParts";

export type GroupMode = { type: "add"; parent: GroupNode } | { type: "rename"; node: GroupNode };

/** A department hangs off the company; a team hangs off a department. */
export function childKind(parent: GroupNode): "department" | "team" {
  return parent.kind === "company" ? "department" : "team";
}

/** Group changes show up wherever a group name or the group list is used. */
export async function invalidateGroupViews(client: ReturnType<typeof useQueryClient>) {
  await Promise.all(
    ["groups", "tasks", "documents", "people"].map((key) =>
      client.invalidateQueries({ queryKey: [key] }),
    ),
  );
}

function GroupForm({ mode, onDone }: { mode: GroupMode; onDone: () => void }) {
  const queryClient = useQueryClient();
  const original = mode.type === "rename" ? mode.node.name : "";
  const [name, setName] = useState(original);
  const [nameError, setNameError] = useState<string | undefined>();
  const [serverError, setServerError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setServerError(null);
    const clean = name.trim();
    if (!clean) {
      setNameError("Enter a name.");
      return;
    }
    setNameError(undefined);
    if (mode.type === "rename" && clean === original) {
      onDone();
      return;
    }
    setBusy(true);
    try {
      if (mode.type === "add") {
        const body: NewGroup = {
          name: clean,
          kind: childKind(mode.parent),
          parent_id: mode.parent.id,
        };
        await apiSend("POST", "/api/groups", body);
      } else {
        await apiSend("PATCH", `/api/groups/${encodeURIComponent(mode.node.id)}`, { name: clean });
      }
      await invalidateGroupViews(queryClient);
      onDone();
    } catch (err) {
      setServerError(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} noValidate className="mt-4 space-y-4">
      <Field label="Name" error={nameError}>
        {(p) => (
          <input
            {...p}
            type="text"
            maxLength={100}
            value={name}
            onChange={(e) => setName(e.target.value)}
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
          {busy ? "Saving…" : mode.type === "add" ? "Add" : "Save"}
        </button>
      </div>
    </form>
  );
}

/** Add a department or team under a group, or rename one. `mode` is null while closed. */
export function GroupDialog({ mode, onClose }: { mode: GroupMode | null; onClose: () => void }) {
  const title =
    mode === null ? "" : mode.type === "rename" ? "Rename group" : `Add ${childKind(mode.parent)}`;
  const description =
    mode === null
      ? ""
      : mode.type === "rename"
        ? `Rename “${mode.node.name}”.`
        : `It will be created under “${mode.parent.name}”.`;
  return (
    <Dialog.Root open={mode !== null} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/40" />
        <Dialog.Content className={dialogContent}>
          <Dialog.Title className="text-lg font-semibold">{title}</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-ink/80">
            {description}
          </Dialog.Description>
          {mode !== null ? (
            <GroupForm
              key={mode.type === "rename" ? mode.node.id : `add-${mode.parent.id}`}
              mode={mode}
              onDone={onClose}
            />
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
