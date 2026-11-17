import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "../test/server";
import { messageFor } from "../lib/messages";
import { ApiError, apiGet, apiSend, apiUpload, onSessionExpired } from "./client";

async function catchError(p: Promise<unknown>): Promise<ApiError> {
  try {
    await p;
  } catch (e) {
    expect(e).toBeInstanceOf(ApiError);
    return e as ApiError;
  }
  throw new Error("expected rejection");
}

describe("api client", () => {
  it("sends csrf header on non-GET", async () => {
    const seen: Record<string, string | null> = {};
    server.use(
      http.all("/api/echo", ({ request }) => {
        seen[request.method] = request.headers.get("x-phoebe-csrf");
        return HttpResponse.json({ ok: true });
      }),
    );
    await apiGet("/api/echo");
    await apiSend("POST", "/api/echo", { a: 1 });
    await apiSend("PATCH", "/api/echo", { a: 1 });
    await apiSend("PUT", "/api/echo", { a: 1 });
    await apiSend("DELETE", "/api/echo");
    await apiUpload("/api/echo", new FormData());
    expect(seen["GET"]).toBeNull();
    for (const m of ["POST", "PATCH", "PUT", "DELETE"]) expect(seen[m]).toBe("1");
  });

  it("sends the csrf header on uploads without forcing a content type", async () => {
    let csrf: string | null = null;
    let type: string | null = null;
    server.use(
      http.post("/api/up", ({ request }) => {
        csrf = request.headers.get("x-phoebe-csrf");
        type = request.headers.get("content-type");
        return HttpResponse.json({ id: 1 });
      }),
    );
    const form = new FormData();
    form.append("file", new Blob(["hi"], { type: "text/markdown" }), "a.md");
    await apiUpload("/api/up", form);
    expect(csrf).toBe("1");
    expect(type).toMatch(/^multipart\/form-data; boundary=/);
  });

  it("sends JSON bodies with a json content type", async () => {
    let body: unknown;
    let type: string | null = null;
    server.use(
      http.post("/api/j", async ({ request }) => {
        type = request.headers.get("content-type");
        body = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    await apiSend("POST", "/api/j", { title: "x" });
    expect(type).toBe("application/json");
    expect(body).toEqual({ title: "x" });
  });

  it("parses error detail into ApiError", async () => {
    server.use(
      http.delete("/api/groups/1", () =>
        HttpResponse.json({ detail: "group_in_use" }, { status: 409 }),
      ),
    );
    const err = await catchError(apiSend("DELETE", "/api/groups/1"));
    expect(err.status).toBe(409);
    expect(err.code).toBe("group_in_use");
    expect(messageFor(err)).toBe("Move or delete its documents, tasks and teams first.");
  });

  it("keeps 415 reason", async () => {
    const reason = "Only PDF, Markdown and CSV files are supported.";
    server.use(
      http.post("/api/documents/upload", () =>
        HttpResponse.json({ detail: "unsupported_type", reason }, { status: 415 }),
      ),
    );
    const err = await catchError(apiUpload("/api/documents/upload", new FormData()));
    expect(err.status).toBe(415);
    expect(err.reason).toBe(reason);
    expect(messageFor(err)).toBe(reason);
  });

  it("204 resolves undefined", async () => {
    server.use(http.delete("/api/x", () => new HttpResponse(null, { status: 204 })));
    await expect(apiSend("DELETE", "/api/x")).resolves.toBeUndefined();
  });

  it("returns parsed JSON for GET", async () => {
    server.use(http.get("/api/me", () => HttpResponse.json({ hello: "world" })));
    await expect(apiGet<{ hello: string }>("/api/me")).resolves.toEqual({ hello: "world" });
  });

  it("session_expired notifies listeners once per response", async () => {
    server.use(
      http.get("/api/me", () => HttpResponse.json({ detail: "session_expired" }, { status: 401 })),
    );
    const a = vi.fn();
    const b = vi.fn();
    const offA = onSessionExpired(a);
    const offB = onSessionExpired(b);
    await catchError(apiGet("/api/me"));
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
    offA();
    await catchError(apiGet("/api/me"));
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(2);
    offB();
  });

  it("does not notify for other 401 codes", async () => {
    server.use(
      http.post("/api/login", () =>
        HttpResponse.json({ detail: "invalid_password" }, { status: 401 }),
      ),
    );
    const listener = vi.fn();
    const off = onSessionExpired(listener);
    const err = await catchError(apiSend("POST", "/api/login", { password: "x" }));
    expect(err.code).toBe("invalid_password");
    expect(listener).not.toHaveBeenCalled();
    off();
  });

  it('non-JSON error body falls back to code "internal_error"', async () => {
    server.use(
      http.get("/api/boom", () => new HttpResponse("<html>bad gateway</html>", { status: 502 })),
    );
    const err = await catchError(apiGet("/api/boom"));
    expect(err.status).toBe(502);
    expect(err.code).toBe("internal_error");
  });

  it("maps a 413 without detail (Lambda's size limit) to file_too_large", async () => {
    server.use(
      http.post("/api/up", () =>
        HttpResponse.json(
          {
            Message: "Request must be smaller than 6291456 bytes for the InvokeFunction operation",
          },
          { status: 413 },
        ),
      ),
    );
    const err = await catchError(apiSend("POST", "/api/up", {}));
    expect(err.status).toBe(413);
    expect(err.code).toBe("file_too_large");
  });

  it("maps FastAPI validation array detail to invalid_request", async () => {
    server.use(
      http.post("/api/v", () =>
        HttpResponse.json({ detail: [{ loc: ["body"], msg: "bad", type: "x" }] }, { status: 422 }),
      ),
    );
    const err = await catchError(apiSend("POST", "/api/v", {}));
    expect(err.code).toBe("invalid_request");
  });
});

describe("messageFor", () => {
  const codes = [
    "invalid_password",
    "session_expired",
    "csrf_required",
    "not_found",
    "group_in_use",
    "sandbox_full",
    "length_required",
    "file_too_large",
    "invalid_group",
    "invalid_link",
    "invalid_request",
    "too_many_attempts",
    "chat_paused",
    "demo_closed",
    "internal_error",
  ];

  it.each(codes)("has copy for %s", (code) => {
    const msg = messageFor(new ApiError(400, code));
    expect(msg.length).toBeGreaterThan(10);
    expect(msg).not.toBe(code);
    expect(msg).not.toBe(messageFor(new ApiError(400, "definitely_unknown_code")));
  });

  it("uses the required copy", () => {
    expect(messageFor(new ApiError(401, "invalid_password"))).toBe("That password didn't work.");
    expect(messageFor(new ApiError(401, "session_expired"))).toBe(
      "Your session ended. Enter the password to start again.",
    );
    expect(messageFor(new ApiError(503, "demo_closed"))).toBe(
      "The Phoebe demo is temporarily offline. Please check back later.",
    );
    // A stopped database (spend limit) reads as the demo being offline.
    expect(messageFor(new ApiError(503, "database_stopped"))).toBe(
      "The Phoebe demo is temporarily offline. Please check back later.",
    );
    const limit = "Rate limit exceeded. Please wait for sessions to refresh.";
    expect(messageFor(new ApiError(429, "chat_paused"))).toBe(limit);
    expect(messageFor(new ApiError(429, "too_many_attempts"))).toBe(limit);
  });

  it("accepts a bare code string", () => {
    expect(messageFor("invalid_password")).toBe("That password didn't work.");
    expect(messageFor("group_in_use")).toBe("Move or delete its documents, tasks and teams first.");
  });

  it("returns the server reason verbatim for unsupported_type", () => {
    const err = new ApiError(415, "unsupported_type", "Only PDF files, sorry.");
    expect(messageFor(err)).toBe("Only PDF files, sorry.");
  });

  it("falls back to a generic message for unsupported_type without a reason", () => {
    expect(messageFor(new ApiError(415, "unsupported_type")).length).toBeGreaterThan(10);
  });

  it("falls back to a generic message for unknown codes and non-errors", () => {
    const generic = messageFor(new ApiError(500, "something_new"));
    expect(generic.length).toBeGreaterThan(10);
    expect(messageFor("something_new")).toBe(generic);
    expect(messageFor(new Error("boom"))).toBe(generic);
    expect(messageFor(undefined)).toBe(generic);
    expect(messageFor({ code: 1 })).toBe(generic);
  });
});
