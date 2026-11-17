import { beforeEach, describe, expect, it } from "vitest";
import type { DocumentOut, GroupNode } from "../api/types";
import { makeDoc } from "../test/fixtures";
import { buildDocTree, loadCollapsed, saveCollapsed } from "./docTree";

const g = (
  id: string,
  kind: GroupNode["kind"],
  parent: string | null,
  children: GroupNode[] = [],
) => ({ id, kind, name: id, owned: false, parent_id: parent, children }) as GroupNode;

const TREE: GroupNode[] = [
  g("co", "company", null, [
    g("eng", "department", "co", [g("plat", "team", "eng")]),
    g("sales", "department", "co"),
  ]),
];

const doc = (id: string, title: string, group_id: string): DocumentOut =>
  makeDoc(id, "team", { title, group_id });

describe("buildDocTree", () => {
  it("keeps all levels down to the group with documents, with subtree counts", () => {
    const tree = buildDocTree(TREE, [doc("1", "B", "plat"), doc("2", "A", "plat")]);
    expect(tree).toHaveLength(1);
    expect(tree[0]!.count).toBe(2);
    expect(tree[0]!.children[0]!.count).toBe(2);
    expect(tree[0]!.children[0]!.children[0]!.count).toBe(2);
    expect(tree[0]!.children[0]!.children[0]!.docs.map((d) => d.title)).toEqual(["A", "B"]);
  });

  it("prunes a sibling with no documents anywhere", () => {
    const tree = buildDocTree(TREE, [doc("1", "A", "plat")]);
    expect(tree[0]!.children.map((c) => c.group.id)).toEqual(["eng"]);
  });

  it("keeps a group's own docs separate from child nodes and counts both", () => {
    const tree = buildDocTree(TREE, [doc("1", "Co", "co"), doc("2", "P", "plat")]);
    expect(tree[0]!.docs.map((d) => d.title)).toEqual(["Co"]);
    expect(tree[0]!.children).toHaveLength(1);
    expect(tree[0]!.count).toBe(2);
  });
});

describe("collapsed storage", () => {
  beforeEach(() => sessionStorage.clear());

  it("round-trips", () => {
    saveCollapsed(new Set(["a", "b"]));
    expect(loadCollapsed()).toEqual(new Set(["a", "b"]));
  });

  it.each(["not json", '{"a":1}', "[1,2]"])("returns an empty set for %s", (raw) => {
    sessionStorage.setItem("phoebe.admin.docs.collapsed", raw);
    expect(loadCollapsed()).toEqual(new Set());
  });
});
