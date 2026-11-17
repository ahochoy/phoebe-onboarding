import type { DocumentOut, GroupNode } from "../api/types";

export interface DocTreeNode {
  group: GroupNode;
  docs: DocumentOut[];
  children: DocTreeNode[];
  /** Documents in this group and everything under it. */
  count: number;
}

/** Groups in their given order, each group's own documents (by title) before its children.
 * Groups with nothing anywhere beneath them are pruned. */
export function buildDocTree(groups: GroupNode[], docs: DocumentOut[]): DocTreeNode[] {
  const byGroup = new Map<string, DocumentOut[]>();
  for (const d of docs) byGroup.set(d.group_id, [...(byGroup.get(d.group_id) ?? []), d]);

  const build = (node: GroupNode): DocTreeNode | null => {
    const own = [...(byGroup.get(node.id) ?? [])].sort((a, b) => a.title.localeCompare(b.title));
    const children = node.children.flatMap((c) => build(c) ?? []);
    const count = own.length + children.reduce((n, c) => n + c.count, 0);
    return count === 0 ? null : { group: node, docs: own, children, count };
  };
  return groups.flatMap((g) => build(g) ?? []);
}

export function groupIds(groups: GroupNode[]): Set<string> {
  const ids = new Set<string>();
  const walk = (nodes: GroupNode[]) =>
    nodes.forEach((n) => {
      ids.add(n.id);
      walk(n.children);
    });
  walk(groups);
  return ids;
}

const KEY = "phoebe.admin.docs.collapsed";

export function loadCollapsed(): Set<string> {
  try {
    const parsed: unknown = JSON.parse(sessionStorage.getItem(KEY) ?? "[]");
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((x): x is string => typeof x === "string"));
  } catch {
    return new Set();
  }
}

export function saveCollapsed(ids: Set<string>): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify([...ids]));
  } catch {
    // Storage can be blocked; the tree just won't remember.
  }
}
