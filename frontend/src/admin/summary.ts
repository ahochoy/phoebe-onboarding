import type { DocumentOut, GroupNode, PersonProgress } from "../api/types";

export interface AdminSummary {
  people: number;
  stillOnboarding: number;
  /** Mean of each person's own completion, 0 to 100. */
  avgCompletion: number;
  documents: number;
  indexed: number;
  processing: number;
  failed: number;
  groups: number;
  /** Checked tasks over all assigned tasks, 0 to 100. */
  taskCompletion: number;
}

const pct = (done: number, total: number) => (total > 0 ? Math.round((done / total) * 100) : 0);

function countGroups(nodes: GroupNode[]): number {
  return nodes.reduce((n, g) => n + 1 + countGroups(g.children), 0);
}

export function summarize(
  people: PersonProgress[],
  docs: DocumentOut[],
  groups: GroupNode[],
): AdminSummary {
  const done = people.reduce((n, p) => n + p.done, 0);
  const total = people.reduce((n, p) => n + p.total, 0);
  const each = people.reduce((n, p) => n + (p.total > 0 ? p.done / p.total : 0), 0);
  return {
    people: people.length,
    stillOnboarding: people.filter((p) => p.done < p.total).length,
    avgCompletion: people.length > 0 ? Math.round((each / people.length) * 100) : 0,
    documents: docs.length,
    indexed: docs.filter((d) => d.status === "indexed").length,
    processing: docs.filter((d) => d.status === "processing").length,
    failed: docs.filter((d) => d.status === "failed").length,
    groups: countGroups(groups),
    taskCompletion: pct(done, total),
  };
}
