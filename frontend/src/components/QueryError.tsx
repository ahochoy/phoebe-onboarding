import { messageFor, STALE_COPY } from "../lib/messages";

/**
 * A query's error. TanStack Query keeps `error` set while earlier data is still
 * cached, so a failed background refetch must not hide a working list: with data
 * on screen (`stale`) the error is a small note beside it; with nothing to show it
 * stands alone as an alert. Renders nothing without an error.
 */
export function QueryError({ error, stale = false }: { error: unknown; stale?: boolean }) {
  if (!error) return null;
  if (stale) {
    return (
      <p role="status" className="text-sm text-danger">
        {STALE_COPY} {messageFor(error)}
      </p>
    );
  }
  return (
    <p role="alert" className="text-sm font-medium text-danger">
      {messageFor(error)}
    </p>
  );
}
