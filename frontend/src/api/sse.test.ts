import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "../test/server";
import { ApiError, onSessionExpired } from "./client";
import { parseSse, streamChat } from "./sse";

const enc = new TextEncoder();

function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

/** A stream that enqueues each chunk as given. */
function streamOf(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
}

async function collect(body: ReadableStream<Uint8Array>) {
  const out: { event: string; data: unknown }[] = [];
  for await (const ev of parseSse(body)) out.push(ev);
  return out;
}

const DONE = {
  text: "PTO is 20 days [1]",
  refused: false,
  reason: null,
  citations: [],
  closest: [],
};

const WIRE =
  frame("meta", { turn_id: "t1" }) +
  frame("delta", { text: "naïve " }) +
  frame("delta", { text: "🎉 [P3]" }) +
  frame("done", DONE);

const EXPECTED = [
  { event: "meta", data: { turn_id: "t1" } },
  { event: "delta", data: { text: "naïve " } },
  { event: "delta", data: { text: "🎉 [P3]" } },
  { event: "done", data: DONE },
];

describe("parseSse", () => {
  it("parses meta, deltas, done in order", async () => {
    expect(await collect(streamOf([enc.encode(WIRE)]))).toEqual(EXPECTED);
  });

  it("byte-by-byte feed gives the same events", async () => {
    const bytes = enc.encode(WIRE);
    const chunks = Array.from(bytes, (b) => Uint8Array.of(b));
    expect(chunks.length).toBe(bytes.length);
    expect(await collect(streamOf(chunks))).toEqual(EXPECTED);
  });

  it("CRLF-free frames only; malformed frame throws", async () => {
    const crlf = streamOf([enc.encode('event: delta\r\ndata: {"text":"x"}\r\n\r\n')]);
    await expect(collect(crlf)).rejects.toEqual(new ApiError(0, "internal_error"));

    const badJson = streamOf([
      enc.encode(frame("meta", { turn_id: "t1" }) + "event: delta\ndata: {nope\n\n"),
    ]);
    const err = await collect(badJson).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 0, code: "internal_error" });

    const noEvent = streamOf([enc.encode('data: {"text":"x"}\n\n')]);
    await expect(collect(noEvent)).rejects.toBeInstanceOf(ApiError);

    const truncated = streamOf([enc.encode('event: delta\ndata: {"te')]);
    await expect(collect(truncated)).rejects.toBeInstanceOf(ApiError);
  });
});

describe("streamChat", () => {
  it("POSTs only the question with the CSRF header and maps events", async () => {
    let seen: { body: unknown; csrf: string | null } | undefined;
    server.use(
      http.post("/api/chat", async ({ request }) => {
        seen = { body: await request.json(), csrf: request.headers.get("X-Phoebe-Csrf") };
        return new HttpResponse(streamOf([enc.encode(WIRE)]), {
          headers: { "Content-Type": "text/event-stream" },
        });
      }),
    );
    const events = [];
    for await (const ev of streamChat("PTO?", new AbortController().signal)) events.push(ev);
    expect(seen).toEqual({ body: { question: "PTO?" }, csrf: "1" });
    expect(events).toEqual([
      { type: "meta", turnId: "t1" },
      { type: "delta", text: "naïve " },
      { type: "delta", text: "🎉 [P3]" },
      { type: "done", done: DONE },
    ]);
  });

  it("a non-200 rejects with ApiError before yielding; 401 notifies session listeners", async () => {
    server.use(
      http.post("/api/chat", () =>
        HttpResponse.json({ detail: "session_expired" }, { status: 401 }),
      ),
    );
    const listener = vi.fn();
    const off = onSessionExpired(listener);
    const it = streamChat("PTO?", new AbortController().signal);
    await expect(it.next()).rejects.toMatchObject({ status: 401, code: "session_expired" });
    expect(listener).toHaveBeenCalledTimes(1);
    off();

    server.use(
      http.post("/api/chat", () => HttpResponse.json({ detail: "demo_closed" }, { status: 503 })),
    );
    const err = await streamChat("PTO?", new AbortController().signal)
      .next()
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 503, code: "demo_closed" });
  });
});
