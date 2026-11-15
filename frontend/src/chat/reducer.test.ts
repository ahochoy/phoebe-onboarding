import { describe, expect, it } from "vitest";
import type { DoneEvent, TurnOut } from "../api/types";
import { messageFor } from "../lib/messages";
import { chatReducer, type ChatMessage } from "./reducer";

const CITE = {
  n: 1,
  chunk_id: "k1",
  document_id: "d1",
  document_title: "Handbook",
  heading_path: "Leave > PTO",
  start: 10,
  end: 40,
};

function sent(question = "How many PTO days do I get?"): ChatMessage[] {
  return chatReducer([], { type: "send", id: "1", question });
}

describe("chatReducer", () => {
  it("send appends the user message and an empty streaming assistant message", () => {
    const state = sent();
    expect(state).toHaveLength(2);
    expect(state[0]).toMatchObject({
      role: "user",
      text: "How many PTO days do I get?",
      status: "done",
    });
    expect(state[1]).toMatchObject({
      role: "assistant",
      text: "",
      status: "streaming",
      refused: false,
    });
  });

  it("done replaces streamed text even when refused", () => {
    let state = sent();
    state = chatReducer(state, { type: "delta", text: "PTO is " });
    state = chatReducer(state, { type: "delta", text: "[P3]" });
    expect(state[1]?.text).toBe("PTO is [P3]");

    const done: DoneEvent = {
      text: "PTO is 20 days [1]",
      refused: false,
      reason: null,
      citations: [CITE],
      closest: [],
    };
    const settled = chatReducer(state, { type: "done", done });
    expect(settled[1]).toMatchObject({
      text: "PTO is 20 days [1]",
      status: "done",
      refused: false,
      citations: [CITE],
    });

    const refusal: DoneEvent = {
      text: "I couldn't find that in your documents.",
      refused: true,
      reason: "no_support",
      citations: [],
      closest: [{ document_id: "d2", title: "Benefits" }],
    };
    const refused = chatReducer(state, { type: "done", done: refusal });
    expect(refused[1]).toMatchObject({
      text: "I couldn't find that in your documents.",
      status: "done",
      refused: true,
      reason: "no_support",
      citations: [],
      closest: [{ document_id: "d2", title: "Benefits" }],
    });
  });

  it("history maps removed citations", () => {
    const turns: TurnOut[] = [
      {
        id: "u1",
        role: "user",
        text: "PTO?",
        refused: false,
        created_at: "2026-11-15T10:00:00Z",
        citations: [],
      },
      {
        id: "a1",
        role: "assistant",
        text: "PTO is 20 days [1] and carries over [2]",
        refused: false,
        created_at: "2026-11-15T10:00:01Z",
        citations: [
          { ...CITE, removed: false },
          { ...CITE, n: 2, document_id: "gone", document_title: "Old policy", removed: true },
        ],
      },
    ];
    const state = chatReducer(sent(), { type: "history", turns });
    expect(state).toHaveLength(2);
    expect(state[0]).toMatchObject({ id: "u1", role: "user", status: "done" });
    expect(state[1]).toMatchObject({ id: "a1", role: "assistant", status: "done", reason: null });
    expect(state[1]?.citations.map((c) => c.removed)).toEqual([false, true]);
  });

  it("error on stream marks message error with mapped copy", () => {
    let state = chatReducer(sent(), { type: "delta", text: "partial" });
    state = chatReducer(state, { type: "error", code: "chat_paused" });
    expect(state[1]).toMatchObject({ status: "error", text: messageFor("chat_paused") });
  });

  it("reset clears the conversation", () => {
    expect(chatReducer(sent(), { type: "reset" })).toEqual([]);
  });
});
