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
  const limited =
    status !== undefined &&
    (status.state === "chat_paused" || status.reasons.some((r) => CAP_REASONS.has(r)));
  return {
    status,
    limited,
    chatAvailable: status?.chat_available ?? false,
    uploadAvailable: status?.upload_available ?? false,
    refresh: () => {
      void query.refetch();
    },
  };
}
