import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

// Handlers are added per test with server.use(...); unhandled requests fail.
// The one default: the fire-and-forget database wake nudge (lib/wake.ts), which
// any signed-in screen may send and no test needs to assert on unless it asks.
export const server = setupServer(
  http.post("/api/wake", () => HttpResponse.json({ database: "awake" })),
);
