import { useQueryClient } from "@tanstack/react-query";
import { Dialog } from "radix-ui";
import { useState, type FormEvent } from "react";
import { apiSend } from "../api/client";
import type { NewTask, TaskPatch, TaskView } from "../api/types";
import { messageFor } from "../lib/messages";
import { Field, dialogContent, inputClass, primaryButton, secondaryButton } from "./formParts";
import { GroupSelect } from "./GroupSelect";

export type TaskTarget = "new" | TaskView;

/** One past the highest position already used in the group, so a task lands last. */
export function nextPosition(tasks: TaskView[], groupId: string): number {
  let max = 0;
  for (const t of tasks) if (t.group_id === groupId && t.position > max) max = t.position;
  return max + 1;
}

/** Admin changes touch the employee checklist and the People counts. */
export async function invalidateTaskViews(client: ReturnType<typeof useQueryClient>) {
  await Promise.all([
    client.invalidateQueries({ queryKey: ["tasks"] }),
    client.invalidateQueries({ queryKey: ["people"] }),
  ]);
}

function TaskForm({
  task,
  tasks,
  onDone,
}: {
  task: TaskView | null;
  tasks: TaskView[];
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const original = {
    title: task?.title ?? "",
    description: task?.description ?? "",
    link: task?.link ?? "",
    groupId: task?.group_id ?? "",
  };
  const [title, setTitle] = useState(original.title);
  const [description, setDescription] = useState(original.description);
  const [link, setLink] = useState(original.link);
  const [groupId, setGroupId] = useState(original.groupId);
  const [titleError, setTitleError] = useState<string | undefined>();
  const [groupError, setGroupError] = useState<string | undefined>();
  const [serverError, setServerError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setServerError(null);
    const titleProblem = title.trim() ? undefined : "Enter a title.";
    const groupProblem = groupId ? undefined : "Choose a group.";
    setTitleError(titleProblem);
    setGroupError(groupProblem);
    if (titleProblem || groupProblem) return;

    const cleanLink = link.trim();
    setBusy(true);
    try {
      if (task === null) {
        const body: NewTask = {
          title: title.trim(),
          description: description.trim(),
          link: cleanLink || null,
          group_id: groupId,
          position: nextPosition(tasks, groupId),
        };
        await apiSend("POST", "/api/tasks", body);
      } else {
        // Only changed fields. A cleared link is an explicit null; title, group_id and
        // position are never null, and an empty description is "".
        const patch: TaskPatch = {};
        if (title.trim() !== original.title) patch.title = title.trim();
        if (description.trim() !== original.description) patch.description = description.trim();
        if (cleanLink !== original.link) patch.link = cleanLink || null;
        if (groupId !== original.groupId) {
          patch.group_id = groupId;
          patch.position = nextPosition(tasks, groupId);
        }
        if (Object.keys(patch).length === 0) {
          onDone();
          return;
        }
        await apiSend("PATCH", `/api/tasks/${encodeURIComponent(task.id)}`, patch);
      }
      await invalidateTaskViews(queryClient);
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
            maxLength={200}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className={inputClass}
          />
        )}
      </Field>
      <Field label="Group" error={groupError}>
        {(p) => <GroupSelect {...p} value={groupId} onChange={setGroupId} />}
      </Field>
      <Field label="Description" optional>
        {(p) => (
          <textarea
            {...p}
            rows={3}
            maxLength={2000}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className={inputClass}
          />
        )}
      </Field>
      <Field label="Link" optional hint="Must start with https://">
        {(p) => (
          <input
            {...p}
            type="url"
            inputMode="url"
            value={link}
            onChange={(e) => setLink(e.target.value)}
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
          {busy ? "Saving…" : task === null ? "Add" : "Save"}
        </button>
      </div>
    </form>
  );
}

/** Add a task, or edit an existing one. `target` is null while closed. */
export function TaskDialog({
  target,
  tasks,
  onClose,
}: {
  target: TaskTarget | null;
  tasks: TaskView[];
  onClose: () => void;
}) {
  const task = target === "new" || target === null ? null : target;
  return (
    <Dialog.Root open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/40" />
        <Dialog.Content className={dialogContent}>
          <Dialog.Title className="text-lg font-semibold">
            {task ? "Edit task" : "Add task"}
          </Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-ink/80">
            {task
              ? "Change how this task appears on the checklist."
              : "New tasks appear last in their group on the matching employees' checklists."}
          </Dialog.Description>
          {target !== null ? (
            <TaskForm key={task?.id ?? "new"} task={task} tasks={tasks} onDone={onClose} />
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
