import { Children, createContext, type ReactNode, useContext, useMemo } from "react";
import Markdown, { type Components } from "react-markdown";
import type { ChatMessage } from "./reducer";

type Cite = ChatMessage["citations"][number];

interface CitedTextProps {
  text: string;
  citations: Cite[];
  /** While streaming, labels like [P3] are raw and shown as-is. */
  settled: boolean;
  onOpen(citation: Cite): void;
}

const MARKER = /\[(\d+)\]/g;

function withMarkers(
  text: string,
  byN: Map<number, Cite>,
  onOpen: (c: Cite) => void,
  key: string,
): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(MARKER)) {
    const n = Number(match[1]);
    const cite = byN.get(n);
    if (!cite) continue;
    const at = match.index;
    if (at > last) out.push(text.slice(last, at));
    if (cite.removed) {
      out.push(
        <span key={`${key}-${at}`} className="text-xs text-ink/70 italic">
          [{n}: source removed]
        </span>,
      );
    } else {
      out.push(
        <button
          key={`${key}-${at}`}
          type="button"
          aria-label={`Source ${n}: ${cite.document_title}`}
          title={cite.document_title}
          onClick={() => onOpen(cite)}
          className="mx-0.5 inline-flex min-h-6 min-w-6 items-center justify-center rounded bg-accent/10 px-1 align-baseline text-xs font-semibold text-accent hover:bg-accent/20"
        >
          [{n}]
        </button>,
      );
    }
    last = at + match[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const ALLOWED = [
  "p",
  "strong",
  "em",
  "ul",
  "ol",
  "li",
  "a",
  "br",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
];
const SAFE_URL = /^(https?:|mailto:)/i;

function safeUrl(url: string): string {
  return SAFE_URL.test(url) ? url : "";
}

interface Markers {
  byN: Map<number, Cite>;
  onOpen(citation: Cite): void;
}

const MarkersContext = createContext<Markers>({ byN: new Map(), onOpen: () => {} });

/** Children with `[n]` markers in their direct text turned into source buttons. */
function Cited({ children, prefix }: { children?: ReactNode; prefix: string }) {
  const { byN, onOpen } = useContext(MarkersContext);
  return Children.map(children, (child, i) =>
    typeof child === "string" ? withMarkers(child, byN, onOpen, `${prefix}${i}`) : child,
  );
}

function Heading({ children }: { children?: ReactNode }) {
  return (
    <h3 className="font-semibold">
      <Cited prefix="h">{children}</Cited>
    </h3>
  );
}

// Module level on purpose: new component identities on each render would make
// React remount the whole answer every time it re-renders.
const COMPONENTS: Components = {
  p: ({ children }) => (
    <p>
      <Cited prefix="p">{children}</Cited>
    </p>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold">
      <Cited prefix="s">{children}</Cited>
    </strong>
  ),
  em: ({ children }) => (
    <em>
      <Cited prefix="e">{children}</Cited>
    </em>
  ),
  li: ({ children }) => (
    <li>
      <Cited prefix="l">{children}</Cited>
    </li>
  ),
  ul: ({ children }) => <ul className="list-disc space-y-1 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal space-y-1 pl-5">{children}</ol>,
  a: ({ href, children }) =>
    href ? (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer nofollow"
        className="text-accent underline"
      >
        {children}
      </a>
    ) : (
      <>{children}</>
    ),
  h1: Heading,
  h2: Heading,
  h3: Heading,
  h4: Heading,
  h5: Heading,
  h6: Heading,
};

/**
 * Answer rendering: a small Markdown subset (paragraphs, bold, italics, lists,
 * headings as h3, http(s)/mailto links). Raw HTML is dropped, images and every
 * other element are unwrapped to their text. `[n]` markers in any text become
 * source buttons once the answer has settled.
 */
export function CitedText({ text, citations, settled, onOpen }: CitedTextProps) {
  const byN = useMemo(
    () => new Map(settled ? citations.map((c) => [c.n, c] as const) : []),
    [citations, settled],
  );
  const markers = useMemo(() => ({ byN, onOpen }), [byN, onOpen]);
  return (
    <MarkersContext value={markers}>
      <div className="space-y-2">
        <Markdown
          allowedElements={ALLOWED}
          unwrapDisallowed
          skipHtml
          urlTransform={safeUrl}
          components={COMPONENTS}
        >
          {text}
        </Markdown>
      </div>
    </MarkersContext>
  );
}
