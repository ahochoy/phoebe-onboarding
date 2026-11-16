import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "../test/server";
import { nudgeWake, WAKE_INTERVAL_MS } from "./wake";

function countWakes() {
  const calls: { csrf: string | null }[] = [];
  server.use(
    http.post("/api/wake", ({ request }) => {
      calls.push({ csrf: request.headers.get("X-Phoebe-Csrf") });
      return HttpResponse.json({ database: "waking" }, { status: 202 });
    }),
  );
  return calls;
}

describe("nudgeWake", () => {
  it("posts /api/wake with the csrf header", async () => {
    const calls = countWakes();
    nudgeWake(1_000);
    await expect.poll(() => calls).toEqual([{ csrf: "1" }]);
  });

  it("sends at most one nudge per interval", async () => {
    const calls = countWakes();
    nudgeWake(1_000);
    nudgeWake(1_000 + WAKE_INTERVAL_MS - 1);
    nudgeWake(1_000 + WAKE_INTERVAL_MS);
    await expect.poll(() => calls.length).toBe(2);
  });

  it("swallows failures", async () => {
    server.use(http.post("/api/wake", () => HttpResponse.json({}, { status: 503 })));
    expect(() => nudgeWake(1_000)).not.toThrow();
  });
});
