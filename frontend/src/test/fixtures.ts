import { delay, http, HttpResponse } from "msw";
import type {
  DocumentDetailOut,
  DocumentOut,
  GroupKind,
  GroupNode,
  Me,
  StatusOut,
  TaskView,
} from "../api/types";
import type { DocSection } from "../documents/sections";
import { server } from "./server";

export const ME: Me = {
  id: "p1",
  name: "Alex Rivera",
  team_id: "t1",
  team_name: "Platform",
  department_id: "d1",
  department_name: "Engineering",
  start_date: "2026-11-10",
  manager: "Sam Lee",
  buddy: "Jo Park",
  day_number: 5,
};

export const OPEN: StatusOut = {
  state: "open",
  chat_available: true,
  upload_available: true,
  reasons: [],
};

export const PAUSED: StatusOut = {
  state: "chat_paused",
  chat_available: false,
  upload_available: true,
  reasons: ["chat_paused"],
};

export const CLOSED: StatusOut = {
  state: "closed",
  chat_available: false,
  upload_available: false,
  reasons: ["demo_closed"],
};

export const GROUPS: GroupNode[] = [
  { id: "c1", kind: "company", name: "Acme Corp", owned: false, parent_id: null, children: [] },
];

export const unauthorized = () => HttpResponse.json({ detail: "session_expired" }, { status: 401 });

/** Counters for the default handlers, so tests can assert on refetches. */
export interface Calls {
  me: number;
  groups: number;
  status: number;
}

/** Registers handlers for a signed-in session. Returns call counters. */
export function useSession(opts: { status?: StatusOut; meDelayMs?: number } = {}): Calls {
  const calls: Calls = { me: 0, groups: 0, status: 0 };
  server.use(
    http.get("/api/me", async () => {
      calls.me += 1;
      if (opts.meDelayMs) await delay(opts.meDelayMs);
      return HttpResponse.json(ME);
    }),
    http.get("/api/status", () => {
      calls.status += 1;
      return HttpResponse.json(opts.status ?? OPEN);
    }),
    http.get("/api/groups", () => {
      calls.groups += 1;
      return HttpResponse.json(GROUPS);
    }),
    // The employee page mounts the tasks and documents panels; tests that care override these.
    http.get("/api/tasks", () => HttpResponse.json([])),
    http.get("/api/documents", () => HttpResponse.json([])),
  );
  return calls;
}

const TIER_NAMES: Record<GroupKind, string> = {
  company: "Acme Corp",
  department: "Engineering",
  team: "Platform",
};

/** Builds one task; override any field. */
export function makeTask(id: string, kind: GroupKind, over: Partial<TaskView> = {}): TaskView {
  return {
    id,
    title: `Task ${id}`,
    description: `Description of task ${id}`,
    link: null,
    group_id: `g-${kind}`,
    group_name: TIER_NAMES[kind],
    group_kind: kind,
    position: 0,
    done: false,
    owned: false,
    ...over,
  };
}

/** Builds one document list row; override any field. */
export function makeDoc(id: string, kind: GroupKind, over: Partial<DocumentOut> = {}): DocumentOut {
  return {
    id,
    title: `Doc ${id}`,
    purpose: `Purpose of doc ${id}`,
    last_updated: "2026-11-03",
    doc_type: "pdf",
    group_id: `g-${kind}`,
    group_name: TIER_NAMES[kind],
    group_kind: kind,
    status: "indexed",
    failure_reason: null,
    public_url: null,
    owned: false,
    ...over,
  };
}

/** Builds a document detail; `sections` are code-point ranges into `full_text`. */
export function makeDetail(
  id: string,
  over: Partial<Omit<DocumentDetailOut, "sections">> & { sections?: DocSection[] } = {},
): DocumentDetailOut {
  return {
    ...makeDoc(id, "company"),
    full_text: null,
    ...over,
    sections: (over.sections ?? []) as unknown as DocumentDetailOut["sections"],
  };
}

/** 14 tasks across the three tiers (4 company, 5 department, 5 team), 6 done. */
export function makeTasks(): TaskView[] {
  const shape: [GroupKind, number, number][] = [
    ["company", 4, 2],
    ["department", 5, 2],
    ["team", 5, 2],
  ];
  return shape.flatMap(([kind, count, done]) =>
    Array.from({ length: count }, (_, i) =>
      makeTask(`${kind}-${i + 1}`, kind, { position: i, done: i < done }),
    ),
  );
}
