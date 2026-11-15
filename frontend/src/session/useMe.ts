import { useQuery, type QueryClient, type UseQueryResult } from "@tanstack/react-query";
import { apiGet } from "../api/client";
import type { Me } from "../api/types";

export function useMe(): UseQueryResult<Me> {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => apiGet<Me>("/api/me"),
    staleTime: 30_000,
  });
}

/** Refetch every active query (used after the sandbox is reset). */
export function invalidateAll(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries();
}

/** Drop all cached server data, e.g. on logout or when the session ends. */
export function forgetSession(queryClient: QueryClient): void {
  queryClient.removeQueries();
  try {
    window.sessionStorage.removeItem("phoebe.welcome");
  } catch {
    // sessionStorage can be blocked; nothing to clear then.
  }
}
