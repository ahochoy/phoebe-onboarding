import type { GroupKind } from "../api/types";

export const TIER_ORDER: GroupKind[] = ["company", "department", "team"];

/** Buckets items by group kind. Input order is kept inside each tier. */
export function groupByTier<T extends { group_kind: GroupKind }>(
  items: T[],
): Record<GroupKind, T[]> {
  const out: Record<GroupKind, T[]> = { company: [], department: [], team: [] };
  for (const item of items) out[item.group_kind].push(item);
  return out;
}
