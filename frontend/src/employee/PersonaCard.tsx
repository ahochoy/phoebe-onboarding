import { formatStart } from "../lib/dates";
import { useMe } from "../session/useMe";
import { PersonAvatar } from "./PersonAvatar";

/**
 * Sticky "Day N · Started date" strip. It must be a direct child of the tasks column's
 * scroll container so `sticky` pins it to that container.
 */
export function DayStrip() {
  const me = useMe();
  if (!me.data) return null;
  const { start_date, day_number } = me.data;
  return (
    <p className="sticky top-0 z-10 bg-surface py-2 text-lg font-semibold text-accent">
      {`Day ${day_number} · Started ${formatStart(start_date)}`}
    </p>
  );
}

function Unassigned({ label }: { label: "Manager" | "Buddy" }) {
  return (
    <div className="flex min-w-0 flex-col items-center gap-1 text-center">
      <span
        aria-hidden="true"
        className="size-16 rounded-full border border-dashed border-ink/30"
      />
      <p className="text-xs uppercase tracking-wide text-ink/70">{label}</p>
      <p className="text-sm font-medium">Not assigned</p>
    </div>
  );
}

/** The manager and buddy, side by side. */
export function PersonaCard() {
  const me = useMe();
  if (!me.data) return null;
  const { manager, buddy, manager_role, buddy_role } = me.data;
  return (
    <div
      role="group"
      aria-label="About you"
      className="grid grid-cols-2 gap-3 rounded-lg border border-ink/15 bg-white p-3"
    >
      {manager ? (
        <PersonAvatar name={manager} role={manager_role} label="Manager" />
      ) : (
        <Unassigned label="Manager" />
      )}
      {buddy ? (
        <PersonAvatar name={buddy} role={buddy_role} label="Buddy" />
      ) : (
        <Unassigned label="Buddy" />
      )}
    </div>
  );
}
