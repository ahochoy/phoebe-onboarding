import { useQuery } from "@tanstack/react-query";
import { Progress } from "radix-ui";
import { useState } from "react";
import { apiGet } from "../api/client";
import type { PersonProgress, TaskView } from "../api/types";
import { formatStart } from "../lib/dates";
import { messageFor } from "../lib/messages";
import { PersonChecklist } from "./PersonChecklist";

// Both keys start with "people", so invalidating ["people"] refreshes the table and any open checklist.
function usePeople() {
  return useQuery({
    queryKey: ["people"],
    queryFn: () => apiGet<PersonProgress[]>("/api/people"),
  });
}

function usePersonTasks(personId: string | null) {
  return useQuery({
    queryKey: ["people", personId, "tasks"],
    queryFn: () => apiGet<TaskView[]>(`/api/people/${personId}/tasks`),
    enabled: personId !== null,
  });
}

function Checklist({ person }: { person: PersonProgress }) {
  const { data, error, isPending } = usePersonTasks(person.person_id);
  if (isPending) {
    return (
      <p role="status" className="text-sm text-ink/80">
        Loading checklist…
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
  return <PersonChecklist name={person.name} tasks={data} />;
}

const th = "px-3 py-2 text-left text-sm font-semibold";
const td = "px-3 py-2 align-middle text-sm";

export function PeopleTab() {
  const { data, error, isPending } = usePeople();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  if (isPending) {
    return (
      <p role="status" className="text-sm text-ink/80">
        Loading people…
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

  const selected = data.find((p) => p.person_id === selectedId) ?? null;

  return (
    <section aria-labelledby="people-heading" className="space-y-4">
      <h2 id="people-heading" className="text-lg font-semibold">
        People &amp; Progress
      </h2>
      {data.length === 0 ? (
        <p className="text-sm text-ink/80">No people yet.</p>
      ) : (
        // The name buttons inside are focusable, so keyboard users can scroll the table sideways.
        <div className="overflow-x-auto rounded-md border border-ink/20 bg-white">
          <table aria-label="People and onboarding progress" className="w-full min-w-xl">
            <thead className="border-b border-ink/20">
              <tr>
                <th scope="col" className={th}>
                  Name
                </th>
                <th scope="col" className={th}>
                  Department › Team
                </th>
                <th scope="col" className={th}>
                  Start date
                </th>
                <th scope="col" className={th}>
                  Progress
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink/10">
              {data.map((p) => {
                const isSelected = p.person_id === selectedId;
                const pct = p.total === 0 ? 0 : (p.done / p.total) * 100;
                return (
                  // The row is a mouse convenience; the name button is the keyboard and
                  // assistive-technology route, and its click bubbles up to this handler.
                  <tr
                    key={p.person_id}
                    onClick={() => setSelectedId(p.person_id)}
                    className={`cursor-pointer hover:bg-surface ${isSelected ? "bg-surface" : ""}`}
                  >
                    <td className={td}>
                      <button
                        type="button"
                        aria-pressed={isSelected}
                        className="inline-flex min-h-6 cursor-pointer items-center font-medium text-accent underline"
                      >
                        {p.name}
                      </button>
                    </td>
                    <td className={td}>
                      {p.department_name ? `${p.department_name} › ${p.team_name}` : p.team_name}
                    </td>
                    <td className={td}>{formatStart(p.start_date)}</td>
                    <td className={td}>
                      <div className="flex min-w-40 items-center gap-3">
                        <Progress.Root
                          value={p.done}
                          max={Math.max(p.total, 1)}
                          aria-label={`${p.name} progress`}
                          className="h-2 min-w-20 flex-1 overflow-hidden rounded-full bg-ink/15"
                        >
                          <Progress.Indicator
                            className="h-full bg-ok transition-[width] duration-300"
                            style={{ width: `${pct}%` }}
                          />
                        </Progress.Root>
                        <span className="whitespace-nowrap">{`${p.done} of ${p.total} done`}</span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {selected ? <Checklist key={selected.person_id} person={selected} /> : null}
    </section>
  );
}
