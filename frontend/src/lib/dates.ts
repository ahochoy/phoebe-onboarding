const startFormat = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

/** Formats an ISO date (`2026-11-10`) as `Nov 10, 2026`; falls back to the input. */
export function formatStart(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? iso : startFormat.format(d);
}
