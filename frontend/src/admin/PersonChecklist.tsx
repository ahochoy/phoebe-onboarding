import { Check, Circle } from "lucide-react";
import type { GroupKind, TaskView } from "../api/types";
import { groupByTier, TIER_ORDER } from "../lib/tiers";

function tierTitle(kind: GroupKind, tasks: TaskView[]): string {
  if (kind === "company") return "Company";
  return tasks[0]?.group_name ?? kind;
}

/** One person's visible tasks grouped by tier, with each task's state shown but never editable. */
export function PersonChecklist({ name, tasks }: { name: string; tasks: TaskView[] }) {
  const tiers = groupByTier(tasks);
  const visible = TIER_ORDER.filter((k) => tiers[k].length > 0);
  const headingId = `checklist-${name.replace(/\s+/g, "-")}`;

  return (
    <section
      aria-labelledby={headingId}
      className="space-y-3 rounded-md border border-ink/20 bg-white p-4"
    >
      <h3 id={headingId} className="text-base font-semibold">
        {`${name}'s checklist`}
      </h3>
      {visible.length === 0 ? (
        <p className="text-sm text-ink/80">No tasks yet.</p>
      ) : (
        visible.map((kind) => (
          <div key={kind}>
            <h4 className="mb-1 text-sm font-semibold">{tierTitle(kind, tiers[kind])}</h4>
            <ul className="divide-y divide-ink/10">
              {tiers[kind].map((task) => (
                <li key={task.id} className="flex items-start gap-3 py-2">
                  {task.done ? (
                    <Check aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-ok" />
                  ) : (
                    <Circle aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-ink/60" />
                  )}
                  <span
                    className={`min-w-0 flex-1 text-sm ${task.done ? "text-ink/70 line-through" : "text-ink"}`}
                  >
                    {task.title}
                  </span>
                  <span
                    className={`shrink-0 text-xs font-medium ${task.done ? "text-ok" : "text-ink/80"}`}
                  >
                    {task.done ? "Done" : "Not done"}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))
      )}
    </section>
  );
}
