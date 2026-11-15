import { Dialog } from "radix-ui";
import { ExternalLink, X } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import { ApiError } from "../api/client";
import type { DocumentDetailOut } from "../api/types";
import { messageFor } from "../lib/messages";
import { MD_UP, useMediaQuery } from "../lib/useMediaQuery";
import { docTypeLabel } from "./DocIcon";
import { buildSections, readSections, type Passage } from "./sections";
import { useDocument } from "./useDocuments";

interface Target {
  docId: string;
  passage: Passage | undefined;
}

const SIDE =
  "fixed top-0 right-0 z-50 flex h-full w-[min(40rem,100vw)] flex-col bg-white shadow-xl";
const SHEET =
  "fixed inset-x-0 bottom-0 z-50 flex h-[92dvh] flex-col rounded-t-xl bg-white shadow-xl";

function isWebUrl(link: string): boolean {
  return /^https?:\/\//i.test(link);
}

function DocumentBody({ doc, passage }: { doc: DocumentDetailOut; passage: Passage | undefined }) {
  const firstMark = useRef<HTMLElement | null>(null);
  const sections = useMemo(
    () => (doc.full_text === null ? [] : buildSections(doc.full_text, readSections(doc), passage)),
    [doc, passage],
  );

  useEffect(() => {
    // Instant under reduced motion; the global CSS rule does not cover scrollIntoView.
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    firstMark.current?.scrollIntoView({ block: "center", behavior: reduced ? "auto" : "smooth" });
  }, [sections]);

  if (doc.status === "processing") {
    return (
      <p role="status" className="text-sm">
        This document is still being processed. Check back in a moment.
      </p>
    );
  }
  if (doc.status === "failed") {
    return (
      <div role="alert" className="text-sm">
        <p className="font-medium text-danger">This document could not be processed.</p>
        {doc.failure_reason ? (
          <p className="mt-1 whitespace-pre-wrap">{doc.failure_reason}</p>
        ) : null}
      </div>
    );
  }
  if (doc.full_text === null) {
    return <p className="text-sm">This document has no text to show.</p>;
  }

  const firstSection = sections.findIndex((s) => s.pieces.some((p) => p.marked));
  const firstPiece = sections[firstSection]?.pieces.findIndex((p) => p.marked) ?? -1;
  return (
    <div className="space-y-4 text-sm leading-relaxed">
      {sections.map((section, i) => (
        <section key={i}>
          {section.heading ? (
            section.level === 2 ? (
              <h2 className="mb-1 text-base font-semibold">{section.heading}</h2>
            ) : (
              <h3 className="mb-1 text-sm font-semibold">{section.heading}</h3>
            )
          ) : null}
          <p className="whitespace-pre-wrap">
            {section.pieces.map((piece, j) => {
              if (!piece.marked) return piece.text;
              return (
                <mark
                  key={j}
                  ref={i === firstSection && j === firstPiece ? firstMark : undefined}
                  className="rounded-sm bg-yellow-200 text-ink"
                >
                  {piece.text}
                </mark>
              );
            })}
          </p>
        </section>
      ))}
    </div>
  );
}

function ViewerContent({ docId, passage }: Target) {
  const { data, error, isPending } = useDocument(docId);

  if (isPending) {
    return (
      <p role="status" className="text-sm">
        Loading document…
      </p>
    );
  }
  if (error) {
    const gone = error instanceof ApiError && error.status === 404;
    return (
      <p role="alert" className="text-sm font-medium text-danger">
        {gone ? "This document is no longer available." : messageFor(error)}
      </p>
    );
  }
  return <DocumentBody doc={data} passage={passage} />;
}

export function DocumentViewer({
  target,
  onClose,
  returnFocusTo,
}: {
  target: Target | null;
  onClose: () => void;
  /** The element that opened the viewer. There is no Dialog.Trigger, so focus is returned by hand. */
  returnFocusTo: { current: HTMLElement | null };
}) {
  const wide = useMediaQuery(MD_UP);
  const { data } = useDocument(target?.docId ?? null);
  const original =
    data && (data.doc_type === "web" || data.doc_type === "google_doc") && data.public_url
      ? data.public_url
      : null;

  return (
    <Dialog.Root open={target !== null} onOpenChange={(next) => !next && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/40" />
        <Dialog.Content
          className={wide ? SIDE : SHEET}
          onCloseAutoFocus={(e) => {
            e.preventDefault();
            returnFocusTo.current?.focus();
          }}
        >
          <header className="flex items-start gap-3 border-b border-ink/15 p-4">
            <div className="min-w-0 flex-1">
              <Dialog.Title asChild>
                <h1 className="text-lg font-semibold break-words">{data?.title ?? "Document"}</h1>
              </Dialog.Title>
              <Dialog.Description className="text-sm text-ink/80">
                {data ? docTypeLabel(data.doc_type) : "Document viewer"}
              </Dialog.Description>
              {original && isWebUrl(original) ? (
                <a
                  href={original}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-1 inline-flex min-h-6 items-center gap-1 text-sm font-medium text-accent underline"
                >
                  View original
                  <span className="sr-only"> (opens in a new tab)</span>
                  <ExternalLink aria-hidden="true" className="size-3.5" />
                </a>
              ) : null}
            </div>
            <Dialog.Close
              aria-label="Close document"
              className="inline-flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-md border border-ink/30"
            >
              <X aria-hidden="true" className="size-4" />
            </Dialog.Close>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {target ? <ViewerContent docId={target.docId} passage={target.passage} /> : null}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
