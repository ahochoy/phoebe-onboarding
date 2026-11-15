import { Accordion, Checkbox, Progress } from "radix-ui";
import { Check, ChevronDown, ExternalLink, PartyPopper } from "lucide-react";
import { useState } from "react";
import type { GroupKind, TaskView } from "../api/types";
import { celebrate } from "../lib/celebrate";
import { messageFor } from "../lib/messages";
import { groupByTier, TIER_ORDER } from "../lib/tiers";
import { useTasks, useToggleTask, type TaskScope } from "./useTasks";

function tierTitle(kind: GroupKind, tasks: TaskView[]): string {
  if (kind === "company") return "Company";
  return tasks[0]?.group_name ?? kind;
}

/** Only plain web links are rendered as links. */
function isWebUrl(link: string): boolean {
  return /^https?:\/\//i.test(link);
}

function TaskRow({ task, onToggle }: { task: TaskView; onToggle: (done: boolean) => void }) {
  const boxId = `task-${task.id}`;
  return (
    <li className="flex items-start gap-3 py-2">
      <Checkbox.Root
        id={boxId}
        checked={task.done}
        onCheckedChange={(v) => onToggle(v === true)}
        className="mt-0.5 flex size-6 shrink-0 cursor-pointer items-center justify-center rounded border-2 border-accent bg-white data-[state=checked]:bg-accent"
      >
        <Checkbox.Indicator>
          <Check aria-hidden="true" className="size-4 text-white" />
        </Checkbox.Indicator>
      </Checkbox.Root>
      <div className="min-w-0 flex-1">
        <label
          htmlFor={boxId}
          className={`block cursor-pointer text-sm font-medium ${task.done ? "text-ink/70 line-through" : "text-ink"}`}
        >
          {task.title}
        </label>
        {task.description ? <p className="text-sm text-ink/80">{task.description}</p> : null}
        {task.link && isWebUrl(task.link) ? (
          <a
            href={task.link}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-1 inline-flex min-h-6 items-center gap-1 text-sm font-medium text-accent underline"
          >
            Open link
            <span className="sr-only"> for {task.title} (opens in a new tab)</span>
            <ExternalLink aria-hidden="true" className="size-3.5" />
          </a>
        ) : null}
      </div>
    </li>
  );
}

export function TasksPanel({ scope = "mine" }: { scope?: TaskScope }) {
  const { data, error, isPending } = useTasks(scope);
  const [toggleError, setToggleError] = useState<unknown>(null);
  const toggle = useToggleTask((err) => setToggleError(err));

  if (isPending) {
    return (
      <p role="status" className="text-sm text-ink/80">
        Loading tasks…
      </p>
    );
  }
  if (error) {
    return (
      <p role="alert" className="text-sm font-medium text-danger">
        {messageFor(error)}
      </p>
    );
  }

  const tasks = data;
  const total = tasks.length;
  const done = tasks.filter((t) => t.done).length;
  const tiers = groupByTier(tasks);
  const visible = TIER_ORDER.filter((k) => tiers[k].length > 0);

  function onToggle(task: TaskView, next: boolean) {
    setToggleError(null);
    const tier = tiers[task.group_kind];
    const completesTier = next && !task.done && tier.every((t) => t.id === task.id || t.done);
    toggle(task, next);
    if (completesTier) celebrate();
  }

  return (
    <section aria-labelledby="tasks-heading" className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h2 id="tasks-heading" className="text-lg font-semibold">
          Tasks
        </h2>
        {total > 0 && done === total ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-ok px-3 py-1 text-sm font-semibold text-white">
            <PartyPopper aria-hidden="true" className="size-4" />
            All done!
          </span>
        ) : null}
      </div>

      <div>
        <p className="mb-1 text-sm font-medium">
          {done} of {total} done
        </p>
        <Progress.Root
          value={done}
          max={Math.max(total, 1)}
          aria-label="Task progress"
          className="h-2 overflow-hidden rounded-full bg-ink/15"
        >
          <Progress.Indicator
            className="h-full bg-ok transition-[width] duration-300"
            style={{ width: `${total === 0 ? 0 : (done / total) * 100}%` }}
          />
        </Progress.Root>
      </div>

      {toggleError ? (
        <p role="alert" className="text-sm font-medium text-danger">
          {messageFor(toggleError)}
        </p>
      ) : null}

      {total === 0 ? (
        <p className="text-sm text-ink/80">No tasks yet.</p>
      ) : (
        <Accordion.Root type="multiple" defaultValue={visible} className="space-y-2">
          {visible.map((kind) => (
            <Accordion.Item
              key={kind}
              value={kind}
              className="rounded-md border border-ink/20 bg-white"
            >
              <Accordion.Header className="m-0">
                <Accordion.Trigger className="group flex min-h-10 w-full cursor-pointer items-center justify-between gap-2 px-3 py-2 text-left text-sm font-semibold">
                  {tierTitle(kind, tiers[kind])}
                  <ChevronDown
                    aria-hidden="true"
                    className="size-4 shrink-0 transition-transform group-data-[state=open]:rotate-180"
                  />
                </Accordion.Trigger>
              </Accordion.Header>
              <Accordion.Content className="px-3 pb-2">
                <ul className="divide-y divide-ink/10">
                  {tiers[kind].map((task) => (
                    <TaskRow key={task.id} task={task} onToggle={(v) => onToggle(task, v)} />
                  ))}
                </ul>
              </Accordion.Content>
            </Accordion.Item>
          ))}
        </Accordion.Root>
      )}
    </section>
  );
}
