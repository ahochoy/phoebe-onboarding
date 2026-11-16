import { formatStart } from "../lib/dates";
import { useMe } from "../session/useMe";

/** Sidebar metadata: start date, manager, buddy and day count. */
export function PersonaCard() {
  const me = useMe();
  if (!me.data) return null;
  const { start_date, manager, buddy, day_number } = me.data;
  const rows: [string, string][] = [
    ["Started", formatStart(start_date)],
    ["Manager", manager ?? "Not assigned"],
    ["Buddy", buddy ?? "Not assigned"],
  ];
  return (
    <div
      role="group"
      aria-label="About you"
      className="rounded-lg border border-ink/15 bg-white p-3"
    >
      <p className="mb-2 text-lg font-semibold text-accent">{`Day ${day_number}`}</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-ink/80">{label}</dt>
            <dd className="font-medium">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
