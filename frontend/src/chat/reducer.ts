import type { Citation, ClosestDoc, DoneEvent, TurnOut } from "../api/types";
import { messageFor, STOPPED_COPY } from "../lib/messages";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  status: "streaming" | "done" | "error";
  refused: boolean;
  reason: DoneEvent["reason"];
  citations: (Citation & { removed?: boolean })[];
  closest: ClosestDoc[];
}

export type ChatAction =
  | { type: "history"; turns: TurnOut[] }
  | { type: "send"; id: string; question: string }
  | { type: "delta"; text: string }
  | { type: "done"; done: DoneEvent }
  | { type: "error"; code: string }
  /** The visitor stopped the answer: settled, not an error. */
  | { type: "stopped" }
  | { type: "reset" };

function base(id: string, role: ChatMessage["role"], text: string): ChatMessage {
  return {
    id,
    role,
    text,
    status: "done",
    refused: false,
    reason: null,
    citations: [],
    closest: [],
  };
}

/** Applies `update` to the assistant message that is still streaming, if any. */
function updateStreaming(
  state: ChatMessage[],
  update: (m: ChatMessage) => ChatMessage,
): ChatMessage[] {
  const last = state.at(-1);
  if (!last || last.role !== "assistant" || last.status !== "streaming") return state;
  return [...state.slice(0, -1), update(last)];
}

export function chatReducer(state: ChatMessage[], action: ChatAction): ChatMessage[] {
  switch (action.type) {
    case "history": {
      // Earlier turns go ahead of anything asked before history arrived, never instead of it.
      const earlier = action.turns.map((t) => ({
        ...base(t.id, t.role, t.text),
        refused: t.refused,
        citations: t.citations,
      }));
      const ids = new Set(earlier.map((m) => m.id));
      return [...earlier, ...state.filter((m) => !ids.has(m.id))];
    }
    case "send":
      return [
        ...state,
        base(`${action.id}-q`, "user", action.question),
        { ...base(`${action.id}-a`, "assistant", ""), status: "streaming" },
      ];
    case "delta":
      return updateStreaming(state, (m) => ({ ...m, text: m.text + action.text }));
    case "done":
      // Streamed deltas carry raw labels like [P3]; done.text is the settled,
      // renumbered answer, so it always replaces what was streamed.
      return updateStreaming(state, (m) => ({
        ...m,
        status: "done",
        text: action.done.text,
        refused: action.done.refused,
        reason: action.done.reason,
        citations: action.done.citations,
        closest: action.done.closest,
      }));
    case "error":
      return updateStreaming(state, (m) => ({
        ...m,
        status: "error",
        text: messageFor(action.code),
        citations: [],
        closest: [],
      }));
    case "stopped":
      return updateStreaming(state, (m) => ({
        ...m,
        status: "done",
        text: STOPPED_COPY,
        citations: [],
        closest: [],
      }));
    case "reset":
      return [];
  }
}
