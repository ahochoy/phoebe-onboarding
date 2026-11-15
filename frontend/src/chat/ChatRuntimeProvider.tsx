import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  type AppendMessage,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiError, apiGet } from "../api/client";
import { streamChat } from "../api/sse";
import type { TurnOut } from "../api/types";
import { messageFor } from "../lib/messages";
import { onDemoReset } from "../state/demoReset";
import { useStatus } from "../state/status";
import { chatReducer, type ChatMessage } from "./reducer";

export interface ChatState {
  messages: ChatMessage[];
  isRunning: boolean;
  /** Text for the single polite live region: the latest settled answer. */
  announcement: string;
  /** False while status is loading, so the paused note does not flash. */
  statusKnown: boolean;
  chatAvailable: boolean;
}

const ChatContext = createContext<ChatState | null>(null);

export function useChat(): ChatState {
  const chat = useContext(ChatContext);
  if (!chat) throw new Error("useChat must be used inside <ChatRuntimeProvider>");
  return chat;
}

function convertMessage(m: ChatMessage): ThreadMessageLike {
  return { id: m.id, role: m.role, content: [{ type: "text", text: m.text }] };
}

function questionOf(message: AppendMessage): string {
  return message.content
    .map((part) => (part.type === "text" ? part.text : ""))
    .join("\n")
    .trim();
}

let seq = 0;

/**
 * Owns the conversation: our reducer is the store, assistant-ui renders it via
 * the external store runtime. One question is in flight at a time.
 */
export function ChatRuntimeProvider({ children }: { children: ReactNode }) {
  const [messages, dispatch] = useReducer(chatReducer, []);
  const [announcement, setAnnouncement] = useState("");
  const inFlight = useRef<AbortController | null>(null);
  const sentAny = useRef(false);
  const { status, chatAvailable, refresh } = useStatus();
  const isRunning = messages.at(-1)?.status === "streaming";

  useEffect(() => {
    let live = true;
    apiGet<TurnOut[]>("/api/chat/history")
      .then((turns) => {
        // A question asked before history arrived wins; never clobber it.
        if (live && !sentAny.current) dispatch({ type: "history", turns });
      })
      .catch(() => {
        // 401s reach the session gate through the client; otherwise start empty.
      });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    const stop = () => {
      inFlight.current?.abort();
      inFlight.current = null;
    };
    const unsubscribe = onDemoReset(() => {
      stop();
      setAnnouncement("");
      dispatch({ type: "reset" });
    });
    return () => {
      unsubscribe();
      stop();
    };
  }, []);

  const send = useCallback(
    async (question: string) => {
      if (inFlight.current) return;
      const controller = new AbortController();
      inFlight.current = controller;
      sentAny.current = true;
      seq += 1;
      setAnnouncement("");
      dispatch({ type: "send", id: `m${seq}`, question });

      const settle = (text: string) => setAnnouncement(text);
      let settled = false;
      try {
        for await (const ev of streamChat(question, controller.signal)) {
          if (ev.type === "delta") {
            dispatch({ type: "delta", text: ev.text });
          } else if (ev.type === "done") {
            dispatch({ type: "done", done: ev.done });
            settle(ev.done.text);
            settled = true;
          } else if (ev.type === "error") {
            dispatch({ type: "error", code: ev.code });
            settle(messageFor(ev.code));
            settled = true;
          }
        }
        if (!settled && !controller.signal.aborted) {
          dispatch({ type: "error", code: "internal_error" });
          settle(messageFor("internal_error"));
        }
      } catch (err) {
        if (controller.signal.aborted) return;
        const code = err instanceof ApiError ? err.code : "internal_error";
        dispatch({ type: "error", code });
        settle(messageFor(code));
      } finally {
        if (inFlight.current === controller) inFlight.current = null;
        // Limits may have moved (or the 503 told us chat is paused): recheck.
        if (!controller.signal.aborted) refresh();
      }
    },
    [refresh],
  );

  const runtime = useExternalStoreRuntime<ChatMessage>({
    messages,
    isRunning,
    isDisabled: !chatAvailable,
    convertMessage,
    onNew: async (message) => {
      const question = questionOf(message);
      if (question) void send(question);
    },
    onCancel: async () => {
      const controller = inFlight.current;
      if (!controller) return;
      inFlight.current = null;
      controller.abort();
      dispatch({ type: "error", code: "cancelled" });
    },
  });

  const value = useMemo<ChatState>(
    () => ({ messages, isRunning, announcement, statusKnown: status !== undefined, chatAvailable }),
    [messages, isRunning, announcement, status, chatAvailable],
  );

  return (
    <ChatContext.Provider value={value}>
      <AssistantRuntimeProvider runtime={runtime}>{children}</AssistantRuntimeProvider>
    </ChatContext.Provider>
  );
}
