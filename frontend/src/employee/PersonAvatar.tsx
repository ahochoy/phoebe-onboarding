import { initials, PHOTOS } from "./photos";

/** A 64px photo (or initials fallback) with a label, the name and, when known, the role. */
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
    <div className="flex min-w-0 flex-col items-center gap-1 text-center">
      {photo ? (
        <img
          src={photo}
          alt={name}
          width={64}
          height={64}
          className="size-16 rounded-full object-cover"
        />
      ) : (
        <span
          role="img"
          aria-label={name}
          className="flex size-16 items-center justify-center rounded-full bg-highlight-soft text-lg font-semibold text-accent"
        >
          <span aria-hidden="true">{initials(name)}</span>
        </span>
      )}
      <p className="text-xs uppercase tracking-wide text-ink/70">{label}</p>
      <p className="text-sm font-medium">{name}</p>
      {role && <p className="text-xs text-ink/70">{role}</p>}
    </div>
  );
}
