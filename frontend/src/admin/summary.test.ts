import { describe, expect, it } from "vitest";
import type { GroupNode, PersonProgress } from "../api/types";
import { makeDoc } from "../test/fixtures";
import { summarize } from "./summary";

const person = (done: number, total: number): PersonProgress =>
  ({ person_id: `p${done}-${total}`, name: "P", done, total }) as PersonProgress;

const node = (id: string, children: GroupNode[] = []): GroupNode =>
  ({ id, kind: "team", name: id, owned: false, parent_id: null, children }) as GroupNode;

describe("summarize", () => {
  it("counts people, who is still onboarding, and the two completion figures", () => {
    const s = summarize([person(2, 4), person(4, 4)], [], []);
    expect(s).toMatchObject({
      people: 2,
      stillOnboarding: 1,
      avgCompletion: 75,
      taskCompletion: 75,
    });
  });

  it("is 0 percent, not NaN, when every total is zero", () => {
    const s = summarize([person(0, 0), person(0, 0)], [], []);
    expect(s.avgCompletion).toBe(0);
    expect(s.taskCompletion).toBe(0);
    expect(summarize([], [], []).avgCompletion).toBe(0);
  });

  it("counts documents by status", () => {
    const docs = [
      makeDoc("a", "company", { status: "indexed" }),
      makeDoc("b", "company", { status: "indexed" }),
      makeDoc("c", "company", { status: "processing" }),
      makeDoc("d", "company", { status: "failed" }),
    ];
    const s = summarize([], docs, []);
    expect([s.documents, s.indexed, s.processing, s.failed]).toEqual([4, 2, 1, 1]);
  });

  it("counts groups across the whole tree", () => {
    const tree = [node("c", [node("d1", [node("t1"), node("t2")]), node("d2", [node("t3")])])];
    expect(summarize([], [], tree).groups).toBe(6);
  });
});
