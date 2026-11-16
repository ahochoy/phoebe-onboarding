import { Cloud, File, FileCode, Globe, Table, type LucideIcon } from "lucide-react";
import type { DocType } from "../api/types";

const TYPES: Record<DocType, { Icon: LucideIcon; label: string }> = {
  pdf: { Icon: File, label: "PDF" },
  markdown: { Icon: FileCode, label: "Markdown" },
  csv: { Icon: Table, label: "CSV" },
  web: { Icon: Globe, label: "Web page" },
  google_doc: { Icon: Cloud, label: "Google Doc" },
};

export function docTypeLabel(type: DocType): string {
  return TYPES[type].label;
}

/** Icon for a document type, with the type name for screen readers. */
export function DocIcon({ type }: { type: DocType }) {
  const { Icon, label } = TYPES[type];
  return (
    <>
      <Icon aria-hidden="true" className="size-5 shrink-0 text-accent" />
      <span className="sr-only">{label}</span>
    </>
  );
}
