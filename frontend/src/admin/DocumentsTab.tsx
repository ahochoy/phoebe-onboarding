import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Info, Link as LinkIcon, Loader2, Pencil, Trash2, Upload } from "lucide-react";
import { useId, useState } from "react";
import { apiGet, apiSend } from "../api/client";
import type { DocumentOut } from "../api/types";
import { formatStart } from "../lib/dates";
import { QueryError } from "../components/QueryError";
import { PAUSED_COPY } from "../lib/messages";
import { useStatus } from "../state/status";
import { AddDocumentDialog, type AddMode } from "./AddDocumentDialog";
import { EditDocumentDialog } from "./EditDocumentDialog";
import { ConfirmDeleteDialog } from "./ConfirmDeleteDialog";
import { buttonClass, iconButton } from "./formParts";

const POLL_MS = 3000;

const TYPE_LABELS: Record<DocumentOut["doc_type"], string> = {
  pdf: "PDF",
  markdown: "Markdown",
  csv: "CSV",
  web: "Web page",
  google_doc: "Google Doc",
};

export function useAdminDocuments() {
  return useQuery({
    queryKey: ["documents", "all"],
    queryFn: () => apiGet<DocumentOut[]>("/api/documents?scope=all"),
    // Indexing happens in the background: keep asking while anything is still processing.
    refetchInterval: (query) =>
      query.state.data?.some((d) => d.status === "processing") ? POLL_MS : false,
  });
}

function StatusCell({ doc }: { doc: DocumentOut }) {
  if (doc.status === "processing") {
    return (
      <span className="inline-flex items-center gap-1.5">
        <Loader2 aria-hidden="true" className="size-4 motion-safe:animate-spin" />
        Processing…
      </span>
    );
  }
  if (doc.status === "failed") {
    return (
      <span className="inline-flex items-start gap-1.5 font-medium text-danger">
        <AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        {`Failed: ${doc.failure_reason ?? ""}`}
      </span>
    );
  }
  return <span className="font-medium text-ok">Indexed ✓</span>;
}

function DeleteDialog({ doc, onClose }: { doc: DocumentOut | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  return (
    <ConfirmDeleteDialog
      open={doc !== null}
      title="Delete this document?"
      description={doc ? `“${doc.title}” will be removed, and Phoebe will stop citing it.` : ""}
      onClose={onClose}
      onConfirm={async () => {
        if (!doc) return;
        await apiSend("DELETE", `/api/documents/${encodeURIComponent(doc.id)}`);
        // ["documents"] covers both the admin list and the employee panel's query.
        await queryClient.invalidateQueries({ queryKey: ["documents"] });
        queryClient.removeQueries({ queryKey: ["document", doc.id] });
      }}
    />
  );
}

const th = "px-3 py-2 text-left text-sm font-semibold";
const td = "px-3 py-2 align-top text-sm";

export function DocumentsTab() {
  const { data, error, isPending } = useAdminDocuments();
  const { uploadAvailable } = useStatus();
  const [addMode, setAddMode] = useState<AddMode | null>(null);
  const [editing, setEditing] = useState<DocumentOut | null>(null);
  const [deleting, setDeleting] = useState<DocumentOut | null>(null);
  const noteId = useId();
  const paused = !uploadAvailable;

  return (
    <section aria-labelledby="documents-heading" className="space-y-4">
      <h2 id="documents-heading" className="text-lg font-semibold">
        Documents
      </h2>
      <div className="space-y-2">
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={paused}
            aria-describedby={paused ? noteId : undefined}
            className={`${buttonClass} bg-accent text-white`}
            onClick={() => setAddMode("file")}
          >
            <Upload aria-hidden="true" className="size-4" />
            Upload document
          </button>
          <button
            type="button"
            disabled={paused}
            aria-describedby={paused ? noteId : undefined}
            className={`${buttonClass} border border-accent/40 text-accent`}
            onClick={() => setAddMode("link")}
          >
            <LinkIcon aria-hidden="true" className="size-4" />
            Add link
          </button>
        </div>
        {paused ? (
          <p id={noteId} className="flex items-start gap-1.5 text-xs text-ink/80">
            <Info aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
            <span>{PAUSED_COPY}</span>
          </p>
        ) : null}
      </div>

      {isPending ? (
        <p role="status" className="text-sm text-ink/80">
          Loading documents…
        </p>
      ) : (
        <QueryError error={error} stale={data !== undefined} />
      )}
      {!data ? null : data.length === 0 ? (
        <p className="text-sm text-ink/80">No documents yet.</p>
      ) : (
        // The row buttons are focusable, so keyboard users can scroll the table sideways.
        <div className="overflow-x-auto rounded-md border border-ink/20 bg-white">
          <table aria-label="Documents" className="w-full min-w-3xl">
            <thead className="border-b border-ink/20">
              <tr>
                {["Title", "Type", "Group", "Purpose", "Last updated", "Status", "Actions"].map(
                  (h) => (
                    <th key={h} scope="col" className={th}>
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-ink/10">
              {data.map((d) => (
                <tr key={d.id}>
                  <td className={`${td} font-medium`}>{d.title}</td>
                  <td className={td}>{TYPE_LABELS[d.doc_type]}</td>
                  <td className={td}>{d.group_name}</td>
                  <td className={td}>{d.purpose}</td>
                  <td className={`${td} whitespace-nowrap`}>
                    {d.last_updated ? (
                      formatStart(d.last_updated)
                    ) : (
                      <>
                        <span aria-hidden="true">—</span>
                        <span className="sr-only">Not set</span>
                      </>
                    )}
                  </td>
                  <td className={td}>
                    <StatusCell doc={d} />
                  </td>
                  <td className={td}>
                    <div className="flex gap-1">
                      <button
                        type="button"
                        aria-label={`Edit ${d.title}`}
                        className={iconButton}
                        onClick={() => setEditing(d)}
                      >
                        <Pencil aria-hidden="true" className="size-4" />
                      </button>
                      <button
                        type="button"
                        aria-label={`Delete ${d.title}`}
                        className={iconButton}
                        onClick={() => setDeleting(d)}
                      >
                        <Trash2 aria-hidden="true" className="size-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <AddDocumentDialog mode={addMode} onClose={() => setAddMode(null)} />
      <EditDocumentDialog doc={editing} onClose={() => setEditing(null)} />
      <DeleteDialog doc={deleting} onClose={() => setDeleting(null)} />
    </section>
  );
}
