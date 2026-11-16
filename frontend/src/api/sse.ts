// Server-sent events for POST /api/chat. EventSource cannot POST, so we read the
// response body ourselves. Frames are `event: <name>\ndata: <json>\n\n`; the
// backend never sends CRLF, so a CR anywhere marks the frame as malformed.

import { ApiError, responseError } from "./client";
import type { DoneEvent } from "./types";

export interface SseEvent {
  event: string;
  data: unknown;
}

export type ChatStreamEvent =
  | { type: "meta"; turnId: string }
  | { type: "delta"; text: string }
  | { type: "done"; done: DoneEvent }
  | { type: "error"; code: string };

function malformed(): ApiError {
  return new ApiError(0, "internal_error");
}

function parseFrame(frame: string): SseEvent {
  if (frame.includes("\r")) throw malformed();
  let event: string | undefined;
  const data: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith(":")) continue; // SSE comment / keep-alive
    const colon = line.indexOf(":");
    if (colon === -1) throw malformed();
    const field = line.slice(0, colon);
    const value = line.slice(colon + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
    else throw malformed();
  }
  if (!event || data.length === 0) throw malformed();
  try {
    return { event, data: JSON.parse(data.join("\n")) as unknown };
  } catch {
    throw malformed();
  }
}

/** Yields one parsed event per frame. Throws ApiError(0, "internal_error") on a malformed frame. */
export async function* parseSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        finished = true;
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      let end = buffer.indexOf("\n\n");
      while (end !== -1) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        if (frame !== "") yield parseFrame(frame);
        end = buffer.indexOf("\n\n");
      }
    }
    buffer += decoder.decode();
    // Anything left over is a frame the server never finished.
    if (buffer.trim() !== "") throw malformed();
  } finally {
    if (!finished) await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

function toChatEvent({ event, data }: SseEvent): ChatStreamEvent | null {
  if (!isRecord(data)) throw malformed();
  switch (event) {
    case "meta":
      if (typeof data.turn_id !== "string") throw malformed();
      return { type: "meta", turnId: data.turn_id };
    case "delta":
      if (typeof data.text !== "string") throw malformed();
      return { type: "delta", text: data.text };
    case "done":
      if (typeof data.text !== "string" || !Array.isArray(data.citations)) throw malformed();
      return {
        type: "done",
        done: {
          text: data.text,
          refused: data.refused === true,
          reason: (data.reason ?? null) as DoneEvent["reason"],
          citations: data.citations as DoneEvent["citations"],
          closest: (Array.isArray(data.closest) ? data.closest : []) as DoneEvent["closest"],
        },
      };
    case "error":
      return { type: "error", code: typeof data.code === "string" ? data.code : "internal_error" };
    default:
      return null; // Unknown events are ignored, per SSE convention.
  }
}

/**
 * Asks one question. Sends only `{question}`. A non-OK response rejects with an
 * ApiError before anything is yielded.
 */
export async function* streamChat(
  question: string,
  signal: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      "X-Phoebe-Csrf": "1",
    },
    credentials: "same-origin",
    body: JSON.stringify({ question }),
    signal,
  });
  if (!res.ok) throw await responseError(res);
  if (!res.body) throw malformed();
  for await (const frame of parseSse(res.body)) {
    const ev = toChatEvent(frame);
    if (ev) yield ev;
  }
}
