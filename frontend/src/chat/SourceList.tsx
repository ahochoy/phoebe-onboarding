import { FileText } from "lucide-react";
import { useId } from "react";
import type { Passage } from "../documents/sections";
import type { ChatMessage } from "./reducer";

type Cite = ChatMessage["citations"][number];

interface SourceListProps {
  citations: Cite[];
  onOpen(documentId: string, passage?: Passage): void;
}

const LINK =
  "inline-flex min-h-6 items-center gap-1 rounded text-left text-accent underline underline-offset-2 hover:no-underline";

/** One entry per cited document, in first-cited order. Opens at its first cited passage. */
export function SourceList({ citations, onOpen }: SourceListProps) {
  const labelId = useId();
  const seen = new Map<string, Cite>();
  for (const c of citations) {
    const prev = seen.get(c.document_id);
    // A document counts as available if any of its citations still is.
    if (!prev || (prev.removed && !c.removed)) seen.set(c.document_id, c);
  }
  const docs = [...seen.values()];
  if (docs.length === 0) return null;
  return (
    <div className="mt-3 border-t border-ink/10 pt-2 text-sm">
      <p id={labelId} className="text-xs font-semibold tracking-wide text-ink/70 uppercase">
        Sources
      </p>
      <ul aria-labelledby={labelId} className="mt-1 space-y-1">
        {docs.map((c) => (
          <li key={c.document_id}>
            {c.removed ? (
              <span className="text-ink/70 italic">source removed</span>
            ) : (
              <button
                type="button"
                className={LINK}
                onClick={() => onOpen(c.document_id, { start: c.start, end: c.end })}
              >
                <FileText aria-hidden="true" className="size-3.5 shrink-0" />
                {c.document_title}
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

interface ClosestListProps {
  closest: ChatMessage["closest"];
  onOpen(documentId: string): void;
}

/** Shown under a refusal: the documents nearest to the question. */
export function ClosestList({ closest, onOpen }: ClosestListProps) {
  const labelId = useId();
  if (closest.length === 0) return null;
  return (
    <div className="mt-3 border-t border-ink/10 pt-2 text-sm">
      <p id={labelId} className="text-xs font-semibold tracking-wide text-ink/70 uppercase">
        Closest documents
      </p>
      <ul aria-labelledby={labelId} className="mt-1 space-y-1">
        {closest.map((d) => (
          <li key={d.document_id}>
            <button type="button" className={LINK} onClick={() => onOpen(d.document_id)}>
              <FileText aria-hidden="true" className="size-3.5 shrink-0" />
              {d.title}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
