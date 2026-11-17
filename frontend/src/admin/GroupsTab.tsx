import { useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { apiSend } from "../api/client";
import type { DocumentOut, GroupNode, TaskView } from "../api/types";
import { useTasks } from "../employee/useTasks";
import { QueryError } from "../components/QueryError";
import { ConfirmDeleteDialog } from "./ConfirmDeleteDialog";
import { iconButton } from "./formParts";
import { useAdminDocuments, useGroups } from "./queries";
import { childKind, GroupDialog, invalidateGroupViews, type GroupMode } from "./GroupDialog";

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

function find(nodes: GroupNode[], id: string): GroupNode | undefined {
  for (const n of nodes) {
    if (n.id === id) return n;
    const hit = find(n.children, id);
    if (hit) return hit;
  }
  return undefined;
}

interface Ctx {
  docs: DocumentOut[];
  tasks: TaskView[];
  selectedId: string | null;
  select: (id: string) => void;
  dialog: (mode: GroupMode) => void;
  remove: (node: GroupNode) => void;
}

const HEADINGS = ["h3", "h4", "h5", "h6"] as const;

function GroupItem({ node, depth, ctx }: { node: GroupNode; depth: number; ctx: Ctx }) {
  const Heading = HEADINGS[Math.min(depth, HEADINGS.length - 1)]!;
  const docCount = ctx.docs.filter((d) => d.group_id === node.id).length;
  const taskCount = ctx.tasks.filter((t) => t.group_id === node.id).length;
  const selected = ctx.selectedId === node.id;
  const canAdd = node.kind !== "team";
  return (
    <li className="space-y-1">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md px-2 py-1">
        <Heading className="min-w-0 text-sm">
          <button
            type="button"
            aria-pressed={selected}
            aria-label={`${node.name}, ${plural(docCount, "document")}, ${plural(taskCount, "task")}`}
            className={`min-h-8 cursor-pointer rounded-md px-2 py-1 text-left ${
              selected ? "bg-accent font-semibold text-white" : "font-medium hover:bg-ink/5"
            }`}
            onClick={() => ctx.select(node.id)}
          >
            {node.name}
            <span className="ml-2 text-xs font-normal">
              {plural(docCount, "doc")} · {plural(taskCount, "task")}
            </span>
          </button>
        </Heading>
        <div className="flex gap-1">
          {canAdd ? (
            <button
              type="button"
              aria-label={`Add ${childKind(node)} to ${node.name}`}
              className={iconButton}
              onClick={() => ctx.dialog({ type: "add", parent: node })}
            >
              <Plus aria-hidden="true" className="size-4" />
            </button>
          ) : null}
          <button
            type="button"
            aria-label={`Rename ${node.name}`}
            className={iconButton}
            onClick={() => ctx.dialog({ type: "rename", node })}
          >
            <Pencil aria-hidden="true" className="size-4" />
          </button>
          {node.kind !== "company" ? (
            <button
              type="button"
              aria-label={`Delete ${node.name}`}
              className={iconButton}
              onClick={() => ctx.remove(node)}
            >
              <Trash2 aria-hidden="true" className="size-4" />
            </button>
          ) : null}
        </div>
      </div>
      {node.children.length > 0 ? (
        <ul className="ml-4 space-y-1 border-l border-ink/15 pl-2">
          {node.children.map((c) => (
            <GroupItem key={c.id} node={c} depth={depth + 1} ctx={ctx} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function Contents({
  node,
  docs,
  tasks,
}: {
  node: GroupNode;
  docs: DocumentOut[];
  tasks: TaskView[];
}) {
  const mine = docs.filter((d) => d.group_id === node.id);
  const myTasks = tasks
    .filter((t) => t.group_id === node.id)
    .sort((a, b) => a.position - b.position);
  return (
    <section
      aria-label={`${node.name} contents`}
      className="space-y-3 rounded-md border border-ink/20 bg-white p-4"
    >
      <h3 className="text-base font-semibold">{node.name}</h3>
      <div>
        <h4 className="text-sm font-semibold">Documents</h4>
        {mine.length === 0 ? (
          <p className="text-sm text-ink/80">No documents.</p>
        ) : (
          <ul className="list-disc pl-5 text-sm">
            {mine.map((d) => (
              <li key={d.id}>{d.title}</li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <h4 className="text-sm font-semibold">Tasks</h4>
        {myTasks.length === 0 ? (
          <p className="text-sm text-ink/80">No tasks.</p>
        ) : (
          <ul className="list-disc pl-5 text-sm">
            {myTasks.map((t) => (
              <li key={t.id}>{t.title}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

export function GroupsTab() {
  const queryClient = useQueryClient();
  const groups = useGroups();
  const docs = useAdminDocuments();
  const tasks = useTasks("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<GroupMode | null>(null);
  const [deleting, setDeleting] = useState<GroupNode | null>(null);

  const error = groups.error ?? docs.error ?? tasks.error;
  const tree = groups.data;
  const allDocs = docs.data;
  const allTasks = tasks.data;
  const selected = tree && selectedId ? find(tree, selectedId) : undefined;

  return (
    <section aria-labelledby="groups-heading" className="space-y-4">
      <h2 id="groups-heading" className="text-lg font-semibold">
        Groups
      </h2>
      {!tree || !allDocs || !allTasks ? (
        error ? (
          <QueryError error={error} />
        ) : (
          <p role="status" className="text-sm text-ink/80">
            Loading groups…
          </p>
        )
      ) : (
        <QueryError error={error} stale />
      )}
      {!tree || !allDocs || !allTasks ? null : (
        <div className="grid items-start gap-4 lg:grid-cols-2">
          <ul aria-label="Groups" className="space-y-1">
            {tree.map((n) => (
              <GroupItem
                key={n.id}
                node={n}
                depth={0}
                ctx={{
                  docs: allDocs,
                  tasks: allTasks,
                  selectedId,
                  select: setSelectedId,
                  dialog: setMode,
                  remove: setDeleting,
                }}
              />
            ))}
          </ul>
          {selected ? <Contents node={selected} docs={allDocs} tasks={allTasks} /> : null}
        </div>
      )}

      <GroupDialog mode={mode} onClose={() => setMode(null)} />
      <ConfirmDeleteDialog
        open={deleting !== null}
        title="Delete this group?"
        description={deleting ? `“${deleting.name}” will be removed.` : ""}
        onClose={() => setDeleting(null)}
        onConfirm={async () => {
          if (!deleting) return;
          await apiSend("DELETE", `/api/groups/${encodeURIComponent(deleting.id)}`);
          await invalidateGroupViews(queryClient);
        }}
      />
    </section>
  );
}
