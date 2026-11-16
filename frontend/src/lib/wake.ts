import { apiSend } from "../api/client";

/** Aurora pauses after 5 idle minutes; one nudge a minute is plenty. */
export const WAKE_INTERVAL_MS = 60_000;

/**
 * How long an answer may show nothing before the chat says Phoebe may be waking
 * up. A warm answer starts in ~3-5 s; a paused database takes ~30 s.
 */
export const WAKING_AFTER_MS = 8_000;

let lastNudge = Number.NEGATIVE_INFINITY;

/**
 * Starts a paused database resuming before the visitor asks anything, so their
 * first question doesn't wait ~30 s. Fire-and-forget and throttled: it never
 * blocks the UI, and a failure only means the next real request wakes it.
 */
export function nudgeWake(now: number = Date.now()): void {
  if (now - lastNudge < WAKE_INTERVAL_MS) return;
  lastNudge = now;
  apiSend("POST", "/api/wake").catch(() => undefined);
}

/** Test-only: forget the last nudge. */
export function resetWake(): void {
  lastNudge = Number.NEGATIVE_INFINITY;
}
