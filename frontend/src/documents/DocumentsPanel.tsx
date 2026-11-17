import { ChevronDown } from "lucide-react";
import { Collapsible } from "radix-ui";
import type { DocumentOut, GroupKind } from "../api/types";
import { PhoebeArt } from "../components/PhoebeArt";
import { QueryError } from "../components/QueryError";
import { groupByTier, TIER_ORDER } from "../lib/tiers";
import { DocIcon } from "./DocIcon";
import { useDocuments } from "./useDocuments";
import { useViewer } from "./ViewerProvider";

function tierTitle(kind: GroupKind, docs: DocumentOut[]): string {
  if (kind === "company") return "Company";
  return docs[0]?.group_name ?? kind;
}

const dateFormat = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeZone: "UTC" });

/** `last_updated` is an ISO date; format it in UTC so the day never shifts. */
function formatDate(iso: string | null): string {
  if (!iso) return "Not dated";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : dateFormat.format(date);
}

function DocRow({ doc, onOpen }: { doc: DocumentOut; onOpen: () => void }) {
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="flex min-h-6 w-full cursor-pointer items-start gap-3 rounded-md px-2 py-2 text-left hover:bg-ink/5"
      >
        <span className="mt-0.5 flex">
          <DocIcon type={doc.doc_type} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-ink">{doc.title}</span>
          {doc.purpose ? <span className="block text-sm text-ink/80">{doc.purpose}</span> : null}
          <span className="block text-xs text-ink/70">
            Updated <span>{formatDate(doc.last_updated)}</span>
            {doc.status === "processing" ? " · Processing" : null}
            {doc.status === "failed" ? " · Failed" : null}
          </span>
        </span>
      </button>
    </li>
  );
}

export function DocumentsPanel() {
  const { data, error, isPending } = useDocuments();
  const viewer = useViewer();

  if (isPending) {
    return (
      <p role="status" className="text-sm text-ink/80">
        Loading documents…
      </p>
    );
  }
  if (!data) return <QueryError error={error} />;
  if (data.length === 0) {
    return (
      <div className="space-y-2">
        <QueryError error={error} stale />
        <div className="flex items-center gap-3">
          <PhoebeArt pose="pointing" size={96} />
          <p className="text-sm text-ink/80">There are no documents for you yet.</p>
        </div>
      </div>
    );
  }

  const tiers = groupByTier(data);
  return (
    <div className="space-y-4">
      <QueryError error={error} stale />
      {TIER_ORDER.filter((k) => tiers[k].length > 0).map((kind) => {
        const docs = tiers[kind];
        const headingId = `docs-tier-${kind}`;
        return (
          <Collapsible.Root key={kind} defaultOpen asChild>
            <section aria-labelledby={headingId}>
              <h3 className="mb-1 text-sm font-semibold text-accent">
                <Collapsible.Trigger
                  id={headingId}
                  className="group flex min-h-8 w-full cursor-pointer items-center justify-between gap-2 rounded-md px-2 text-left hover:bg-highlight-soft"
                >
                  {tierTitle(kind, docs)}
                  <ChevronDown
                    aria-hidden="true"
                    className="size-4 shrink-0 transition-transform group-data-[state=open]:rotate-180"
                  />
                </Collapsible.Trigger>
              </h3>
              <Collapsible.Content>
                <ul>
                  {docs.map((doc) => (
                    <DocRow key={doc.id} doc={doc} onOpen={() => viewer.open(doc.id)} />
                  ))}
                </ul>
              </Collapsible.Content>
            </section>
          </Collapsible.Root>
        );
      })}
    </div>
  );
}
