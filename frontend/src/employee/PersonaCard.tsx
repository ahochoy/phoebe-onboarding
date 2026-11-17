import { formatStart } from "../lib/dates";
import { useMe } from "../session/useMe";
import { PersonAvatar } from "./PersonAvatar";

/**
 * Sticky card with who you are and where you are in onboarding. It must be a direct
 * child of the tasks column's scroll container so `sticky` pins it to that container.
 */
export function ProfileCard() {
  const me = useMe();
  if (!me.data) return null;
  const { name, team_name, start_date, day_number } = me.data;
  return (
    <div
      role="group"
      aria-label="Your profile"
      className="sticky top-0 z-10 rounded-lg border border-ink/15 bg-white p-3"
    >
      <p className="text-lg font-semibold text-accent">{name}</p>
      <p className="text-sm text-ink/80">{team_name}</p>
      <p className="mt-1 text-sm font-medium">
        {`Day ${day_number} · Started ${formatStart(start_date)}`}
      </p>
    </div>
  );
}

function Unassigned({ label }: { label: "Manager" | "Buddy" }) {
  return (
    <div className="flex min-w-0 flex-row items-center gap-3">
      <span
        aria-hidden="true"
        className="size-14 shrink-0 rounded-full border border-dashed border-ink/30"
      />
      <div className="min-w-0">
        <p className="text-xs uppercase tracking-wide text-ink/70">{label}</p>
        <p className="text-sm font-medium">Not assigned</p>
      </div>
    </div>
  );
}

/** The manager above the buddy: one row each, avatar on the left. */
export function PersonaCard() {
  const me = useMe();
  if (!me.data) return null;
  const { manager, buddy, manager_role, buddy_role } = me.data;
  return (
    <div role="group" aria-label="About you" className="flex flex-col gap-3 px-1">
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
