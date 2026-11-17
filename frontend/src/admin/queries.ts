import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../api/client";
import type { DocumentOut, GroupNode } from "../api/types";

const POLL_MS = 3000;

export function useAdminDocuments() {
  return useQuery({
    queryKey: ["documents", "all"],
    queryFn: () => apiGet<DocumentOut[]>("/api/documents?scope=all"),
    // Indexing happens in the background: keep asking while anything is still processing.
    refetchInterval: (query) =>
      query.state.data?.some((d) => d.status === "processing") ? POLL_MS : false,
  });
}

export function useGroups() {
  return useQuery({
    queryKey: ["groups"],
    queryFn: () => apiGet<GroupNode[]>("/api/groups"),
  });
}
