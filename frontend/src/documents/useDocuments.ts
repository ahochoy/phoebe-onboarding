import { useQuery } from "@tanstack/react-query";
import { ApiError, apiGet } from "../api/client";
import type { DocumentDetailOut, DocumentOut } from "../api/types";

export function useDocuments() {
  return useQuery({
    queryKey: ["documents", "mine"],
    queryFn: () => apiGet<DocumentOut[]>("/api/documents?scope=mine"),
  });
}

export function useDocument(id: string | null) {
  return useQuery({
    queryKey: ["document", id],
    queryFn: () => apiGet<DocumentDetailOut>(`/api/documents/${encodeURIComponent(id ?? "")}`),
    enabled: id !== null,
    // A deleted or hidden document will not come back; do not keep asking.
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });
}
