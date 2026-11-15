import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Info, Link as LinkIcon, Loader2, Pencil, Trash2, Upload } from "lucide-react";
import { AlertDialog } from "radix-ui";
import { useId, useState } from "react";
import { apiGet, apiSend } from "../api/client";
import type { DocumentOut } from "../api/types";
import { formatStart } from "../lib/dates";
import { messageFor, PAUSED_COPY } from "../lib/messages";
import { useStatus } from "../state/status";
import { AddDocumentDialog, type AddMode } from "./AddDocumentDialog";
import { EditDocumentDialog } from "./EditDocumentDialog";
import { buttonClass, dialogContent, primaryButton, secondaryButton } from "./formParts";

const POLL_MS = 3000;

const TYPE_LABELS: Record<DocumentOut["doc_type"], string> = {
  pdf: "PDF",
  markdown: "Markdown",
  csv: "CSV",
  web: "Web page",
  google_doc: "Google Doc",
};

function useAdminDocuments() {
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    if (!doc) return;
    setBusy(true);
    setError(null);
    try {
      await apiSend("DELETE", `/api/documents/${encodeURIComponent(doc.id)}`);
      // ["documents"] covers both the admin list and the employee panel's query.
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      queryClient.removeQueries({ queryKey: ["document", doc.id] });
      onClose();
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AlertDialog.Root
      open={doc !== null}
      onOpenChange={(open) => {
        if (busy) return;
        if (!open) {
          setError(null);
          onClose();
        }
      }}
    >
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 z-40 bg-ink/40" />
        <AlertDialog.Content className={dialogContent}>
          <AlertDialog.Title className="text-lg font-semibold">
            Delete this document?
          </AlertDialog.Title>
          <AlertDialog.Description className="mt-2 text-sm">
            {doc ? `“${doc.title}” will be removed, and Phoebe will stop citing it.` : ""}
          </AlertDialog.Description>
          {error ? (
            <p role="alert" className="mt-3 text-sm font-medium text-danger">
              {error}
            </p>
          ) : null}
          <div className="mt-5 flex justify-end gap-2">
            <AlertDialog.Cancel asChild>
              <button type="button" disabled={busy} className={secondaryButton}>
                Cancel
              </button>
            </AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <button
                type="button"
                disabled={busy}
                className={primaryButton}
                onClick={(e) => {
                  // Stay open until the request finishes.
                  e.preventDefault();
                  void confirm();
                }}
              >
                Yes, delete
              </button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}

const th = "px-3 py-2 text-left text-sm font-semibold";
const td = "px-3 py-2 align-top text-sm";
const iconButton =
  "inline-flex size-8 cursor-pointer items-center justify-center rounded-md border border-ink/30 text-ink hover:bg-ink/5";

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
      ) : error ? (
        <p role="alert" className="text-sm font-medium text-danger">
          {messageFor(error)}
        </p>
      ) : data.length === 0 ? (
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
