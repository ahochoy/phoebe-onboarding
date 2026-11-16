import type { DocumentDetailOut } from "../api/types";
import { cpToUtf16 } from "../lib/offsets";

/** One section of a document. Offsets are code points into `full_text`. */
export interface DocSection {
  heading_path: string[];
  start: number;
  end: number;
}

export interface Passage {
  start: number;
  end: number;
}

/** A run of text inside a section, optionally highlighted. */
export interface Piece {
  text: string;
  marked: boolean;
}

export interface RenderedSection {
  heading: string | null;
  /** 2 for a top-level heading, 3 for anything deeper. */
  level: 2 | 3;
  pieces: Piece[];
}

/** The API types sections loosely; narrow them and drop anything malformed. */
export function readSections(detail: DocumentDetailOut): DocSection[] {
  const out: DocSection[] = [];
  for (const raw of detail.sections) {
    const { heading_path, start, end } = raw as Record<string, unknown>;
    if (
      Array.isArray(heading_path) &&
      heading_path.every((h) => typeof h === "string") &&
      typeof start === "number" &&
      typeof end === "number"
    ) {
      out.push({ heading_path: heading_path as string[], start, end });
    }
  }
  return out;
}

/**
 * Slices `text` by section and splits each slice around the intersection with
 * `passage`, so a passage that spans sections is highlighted in all of them.
 * With no sections the whole text is one headingless block.
 */
export function buildSections(
  text: string,
  sections: DocSection[],
  passage: Passage | undefined,
): RenderedSection[] {
  const spans: DocSection[] = sections.length
    ? sections
    : [{ heading_path: [], start: 0, end: Number.MAX_SAFE_INTEGER }];

  return spans.map((section) => {
    const from = cpToUtf16(text, section.start);
    const to = Math.max(from, cpToUtf16(text, section.end));
    const body = text.slice(from, to);
    const path = section.heading_path;
    const heading = path.length ? (path[path.length - 1] ?? null) : null;
    const level: 2 | 3 = path.length > 1 ? 3 : 2;

    const lo = passage ? Math.max(section.start, passage.start) : 0;
    const hi = passage ? Math.min(section.end, passage.end) : 0;
    if (!passage || lo >= hi) {
      return { heading, level, pieces: [{ text: body, marked: false }] };
    }
    const a = Math.min(Math.max(cpToUtf16(text, lo), from), to) - from;
    const b = Math.min(Math.max(cpToUtf16(text, hi), from), to) - from;
    const pieces: Piece[] = [
      { text: body.slice(0, a), marked: false },
      { text: body.slice(a, b), marked: true },
      { text: body.slice(b), marked: false },
    ].filter((p) => p.text.length > 0);
    return { heading, level, pieces };
  });
}
