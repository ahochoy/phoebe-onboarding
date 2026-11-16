import { useQuery, type QueryClient, type UseQueryResult } from "@tanstack/react-query";
import { apiGet } from "../api/client";
import type { Me } from "../api/types";

/** Set once this tab has held a live session; the "session ended" copy needs it. */
export const HAD_SESSION_KEY = "phoebe.hadSession";

export function markHadSession(): void {
  try {
    window.sessionStorage.setItem(HAD_SESSION_KEY, "1");
  } catch {
    // Storage can throw (Safari private mode); the message is then simply not shown.
  }
}

export function clearHadSession(): void {
  try {
    window.sessionStorage.removeItem(HAD_SESSION_KEY);
  } catch {
    // Nothing to clear when storage is blocked.
  }
}

export function hadSession(): boolean {
  try {
    return window.sessionStorage.getItem(HAD_SESSION_KEY) !== null;
  } catch {
    return false;
  }
}

export function useMe(): UseQueryResult<Me> {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      const me = await apiGet<Me>("/api/me");
      markHadSession();
      return me;
    },
    staleTime: 30_000,
  });
}

/** Refetch every active query (used after the sandbox is reset). */
export function invalidateAll(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries();
}

/**
 * Drop all cached server data, e.g. on logout or when the session ends. The
 * had-session marker is deliberately kept: an expiry must still be able to
 * say "your session ended". Logout clears it explicitly.
 */
export function forgetSession(queryClient: QueryClient): void {
  queryClient.removeQueries();
  try {
    window.sessionStorage.removeItem("phoebe.welcome");
  } catch {
    // sessionStorage can be blocked; nothing to clear then.
  }
}
