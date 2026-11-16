import { describe, expect, it } from "vitest";
import { groupByTier, TIER_ORDER } from "./tiers";

describe("groupByTier", () => {
  it("buckets by kind and keeps input order inside each tier", () => {
    const items = [
      { id: "a", group_kind: "team" as const },
      { id: "b", group_kind: "company" as const },
      { id: "c", group_kind: "team" as const },
      { id: "d", group_kind: "department" as const },
      { id: "e", group_kind: "company" as const },
    ];
    const out = groupByTier(items);
    expect(out.company.map((i) => i.id)).toEqual(["b", "e"]);
    expect(out.department.map((i) => i.id)).toEqual(["d"]);
    expect(out.team.map((i) => i.id)).toEqual(["a", "c"]);
  });

  it("returns an empty bucket for every tier when given nothing", () => {
    expect(groupByTier([])).toEqual({ company: [], department: [], team: [] });
  });

  it("orders tiers company, department, team", () => {
    expect(TIER_ORDER).toEqual(["company", "department", "team"]);
  });
});
