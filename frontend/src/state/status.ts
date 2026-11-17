import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../api/client";
import type { StatusOut } from "../api/types";

const POLL_MS = 60_000;

const CAP_REASONS: ReadonlySet<StatusOut["reasons"][number]> = new Set([
  "session_chat_limit",
  "global_chat_limit",
  "session_upload_limit",
  "global_upload_limit",
]);

export interface UseStatus {
  status: StatusOut | undefined;
  /** Paused by the spend budget (or `make pause`): the spend banner shows. */
  paused: boolean;
  /** A per-session or global rate-limit cap applies: the pill shows. */
  capped: boolean;
  /** Either of the two. */
  limited: boolean;
  chatAvailable: boolean;
  uploadAvailable: boolean;
  refresh(): void;
}

/** Public demo status. Polls once a minute while the tab is visible. */
export function useStatus(): UseStatus {
  const query = useQuery({
    queryKey: ["status"],
    queryFn: () => apiGet<StatusOut>("/api/status"),
    refetchInterval: () => (document.visibilityState === "visible" ? POLL_MS : false),
    refetchOnWindowFocus: true,
  });
  const status = query.data;
  const paused = status?.state === "chat_paused";
  const capped = status !== undefined && status.reasons.some((r) => CAP_REASONS.has(r));
  return {
    status,
    paused,
    capped,
    limited: paused || capped,
    chatAvailable: status?.chat_available ?? false,
    uploadAvailable: status?.upload_available ?? false,
    refresh: () => {
      void query.refetch();
    },
  };
}
