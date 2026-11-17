import { initials, PHOTOS } from "./photos";

/** One row: a 56px photo (or initials fallback) on the left; label, name and role on the right. */
export function PersonAvatar({
  name,
  role,
  label,
}: {
  name: string;
  role: string | null;
  label: "Manager" | "Buddy";
}) {
  const photo = PHOTOS[name];
  return (
    <div className="flex min-w-0 flex-row items-center gap-3">
      {photo ? (
        <img
          src={photo}
          alt=""
          width={56}
          height={56}
          className="size-14 shrink-0 rounded-full object-cover"
        />
      ) : (
        <span
          aria-hidden="true"
          className="flex size-14 shrink-0 items-center justify-center rounded-full bg-highlight-soft text-lg font-semibold text-accent"
        >
          {initials(name)}
        </span>
      )}
      <div className="min-w-0">
        <p className="text-xs uppercase tracking-wide text-ink/70">{label}</p>
        <p className="text-sm font-medium">{name}</p>
        {role && <p className="text-xs text-ink/70">{role}</p>}
      </div>
    </div>
  );
}
