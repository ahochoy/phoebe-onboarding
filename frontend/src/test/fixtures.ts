import { delay, http, HttpResponse } from "msw";
import type { GroupNode, Me, StatusOut } from "../api/types";
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
  );
  return calls;
}
