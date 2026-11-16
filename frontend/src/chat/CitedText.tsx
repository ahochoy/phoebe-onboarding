import type { ReactNode } from "react";
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

/**
 * Plain-text answer rendering: blank lines split paragraphs and lines starting
 * with `#` become h3 headings. No HTML or Markdown is ever interpreted.
 */
export function CitedText({ text, citations, settled, onOpen }: CitedTextProps) {
  const byN = new Map(settled ? citations.map((c) => [c.n, c] as const) : []);
  const blocks = toBlocks(text);
  return (
    <div className="space-y-2">
      {blocks.map((block, i) => {
        const key = `b${i}`;
        return block.heading ? (
          <h3 key={key} className="font-semibold">
            {withMarkers(block.text, byN, onOpen, key)}
          </h3>
        ) : (
          <p key={key} className="whitespace-pre-wrap">
            {withMarkers(block.text, byN, onOpen, key)}
          </p>
        );
      })}
    </div>
  );
}

interface Block {
  heading: boolean;
  text: string;
}

/** Blank lines end a paragraph; a `#` line is its own heading block. */
function toBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length > 0) blocks.push({ heading: false, text: para.join("\n") });
    para = [];
  };
  for (const line of text.split("\n")) {
    if (line.trim() === "") {
      flush();
    } else if (line.startsWith("#")) {
      flush();
      blocks.push({ heading: true, text: line.replace(/^#+\s*/, "") });
    } else {
      para.push(line);
    }
  }
  flush();
  return blocks;
}
