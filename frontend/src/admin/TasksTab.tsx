import { useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Pencil, Plus, Trash2 } from "lucide-react";
import { useId, useState } from "react";
import { apiSend } from "../api/client";
import type { TaskView } from "../api/types";
import { useTasks } from "../employee/useTasks";
import { messageFor } from "../lib/messages";
import { TIER_ORDER } from "../lib/tiers";
import { ConfirmDeleteDialog } from "./ConfirmDeleteDialog";
import { buttonClass, iconButton } from "./formParts";
import { invalidateTaskViews, TaskDialog, type TaskTarget } from "./TaskDialog";

interface Section {
  id: string;
  name: string;
  tasks: TaskView[];
}

/** One section per group: company first, then departments, then teams; tasks by position. */
function sections(tasks: TaskView[]): Section[] {
  const byGroup = new Map<string, TaskView[]>();
  for (const t of tasks) byGroup.set(t.group_id, [...(byGroup.get(t.group_id) ?? []), t]);
  return [...byGroup.entries()]
    .map(([id, list]) => ({
      id,
      name: list[0]!.group_name,
      tier: TIER_ORDER.indexOf(list[0]!.group_kind),
      tasks: [...list].sort((a, b) => a.position - b.position),
    }))
    .sort((a, b) => a.tier - b.tier || a.name.localeCompare(b.name));
}

function TaskGroup({
  section,
  locked,
  onMove,
  onEdit,
  onDelete,
}: {
  section: Section;
  locked: boolean;
  onMove: (list: TaskView[], from: number, to: number) => void;
  onEdit: (t: TaskView) => void;
  onDelete: (t: TaskView) => void;
}) {
  const headingId = useId();
  const last = section.tasks.length - 1;
  return (
    <section aria-labelledby={headingId} className="space-y-2">
      <h3 id={headingId} className="text-base font-semibold">
        {section.name}
      </h3>
      <ul className="divide-y divide-ink/10 rounded-md border border-ink/20 bg-white">
        {section.tasks.map((t, i) => (
          <li key={t.id} className="flex flex-wrap items-start justify-between gap-3 px-3 py-2">
            <div className="min-w-0 flex-1">
              <h4 className="text-sm font-medium">{t.title}</h4>
              {t.description ? <p className="mt-0.5 text-sm text-ink/80">{t.description}</p> : null}
              {t.link ? (
                <a
                  href={t.link}
                  className="mt-0.5 inline-block text-sm break-all text-accent underline"
                >
                  {t.link}
                </a>
              ) : null}
            </div>
            <div className="flex gap-1">
              <button
                type="button"
                aria-label={`Move up ${t.title}`}
                disabled={locked || i === 0}
                className={iconButton}
                onClick={() => onMove(section.tasks, i, i - 1)}
              >
                <ArrowUp aria-hidden="true" className="size-4" />
              </button>
              <button
                type="button"
                aria-label={`Move down ${t.title}`}
                disabled={locked || i === last}
                className={iconButton}
                onClick={() => onMove(section.tasks, i, i + 1)}
              >
                <ArrowDown aria-hidden="true" className="size-4" />
              </button>
              <button
                type="button"
                aria-label={`Edit ${t.title}`}
                className={iconButton}
                onClick={() => onEdit(t)}
              >
                <Pencil aria-hidden="true" className="size-4" />
              </button>
              <button
                type="button"
                aria-label={`Delete ${t.title}`}
                className={iconButton}
                onClick={() => onDelete(t)}
              >
                <Trash2 aria-hidden="true" className="size-4" />
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function TasksTab() {
  const queryClient = useQueryClient();
  const { data, error, isPending } = useTasks("all");
  const [dialog, setDialog] = useState<TaskTarget | null>(null);
  const [deleting, setDeleting] = useState<TaskView | null>(null);
  const [swapping, setSwapping] = useState(false);
  const [swapError, setSwapError] = useState<string | null>(null);

  const patchPosition = (t: TaskView, position: number) =>
    apiSend("PATCH", `/api/tasks/${encodeURIComponent(t.id)}`, { position });

  /**
   * Move the task at index `i` to index `j` (a neighbour) in its group's displayed order,
   * one move at a time. With strictly increasing positions this swaps the two positions
   * (two PATCHes, in order; if the second fails the first is rolled back, best effort).
   * With tied or out-of-order positions a plain swap could change nothing, so the group
   * is renumbered 1..N in the new order instead, PATCHing only tasks whose position changes.
   */
  async function move(list: TaskView[], i: number, j: number) {
    if (swapping) return;
    setSwapping(true);
    setSwapError(null);
    try {
      const a = list[i]!;
      const b = list[j]!;
      const clean = list.every((t, k) => k === 0 || list[k - 1]!.position < t.position);
      if (clean) {
        await patchPosition(a, b.position);
        try {
          await patchPosition(b, a.position);
        } catch (err) {
          await patchPosition(a, a.position).catch(() => undefined);
          throw err;
        }
      } else {
        const next = [...list];
        next[i] = b;
        next[j] = a;
        for (const [k, t] of next.entries()) {
          if (t.position !== k + 1) await patchPosition(t, k + 1);
        }
      }
    } catch (err) {
      setSwapError(messageFor(err));
    } finally {
      // Refetch either way, so a half-applied swap shows what the server really has.
      await invalidateTaskViews(queryClient);
      setSwapping(false);
    }
  }

  return (
    <section aria-labelledby="tasks-heading" className="space-y-4">
      <h2 id="tasks-heading" className="text-lg font-semibold">
        Tasks
      </h2>
      <button
        type="button"
        className={`${buttonClass} bg-accent text-white`}
        onClick={() => setDialog("new")}
      >
        <Plus aria-hidden="true" className="size-4" />
        Add task
      </button>
      {swapError ? (
        <p role="alert" className="text-sm font-medium text-danger">
          {swapError}
        </p>
      ) : null}

      {isPending ? (
        <p role="status" className="text-sm text-ink/80">
          Loading tasks…
        </p>
      ) : error ? (
        <p role="alert" className="text-sm font-medium text-danger">
          {messageFor(error)}
        </p>
      ) : data.length === 0 ? (
        <p className="text-sm text-ink/80">No tasks yet.</p>
      ) : (
        <div className="space-y-5">
          {sections(data).map((s) => (
            <TaskGroup
              key={s.id}
              section={s}
              locked={swapping}
              onMove={(l, f, t) => void move(l, f, t)}
              onEdit={setDialog}
              onDelete={setDeleting}
            />
          ))}
        </div>
      )}

      <TaskDialog target={dialog} tasks={data ?? []} onClose={() => setDialog(null)} />
      <ConfirmDeleteDialog
        open={deleting !== null}
        title="Delete this task?"
        description={
          deleting
            ? `“${deleting.title}” will be removed from every checklist, along with its completion records.`
            : ""
        }
        onClose={() => setDeleting(null)}
        onConfirm={async () => {
          if (!deleting) return;
          await apiSend("DELETE", `/api/tasks/${encodeURIComponent(deleting.id)}`);
          await invalidateTaskViews(queryClient);
        }}
      />
    </section>
  );
}
