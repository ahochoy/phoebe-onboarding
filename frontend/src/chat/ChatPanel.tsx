import { ComposerPrimitive, MessagePrimitive, ThreadPrimitive } from "@assistant-ui/react";
import { AlertCircle, Info, SendHorizontal } from "lucide-react";
import { useId } from "react";
import { Mascot } from "../components/Mascot";
import { useViewer } from "../documents/ViewerProvider";
import { PAUSED_COPY } from "../lib/messages";
import { useChat } from "./ChatRuntimeProvider";
import { CitedText } from "./CitedText";
import type { ChatMessage } from "./reducer";
import { ClosestList, SourceList } from "./SourceList";

const SUGGESTED = [
  "How many PTO days do I get?",
  "What's on my first-week schedule?",
  "Who's who on the Platform team?",
  "How does on-call work?",
];

function Greeting() {
  return (
    <div className="flex flex-col items-center gap-3 px-4 py-8 text-center">
      <Mascot size={56} />
      <p className="max-w-sm text-sm">
        Hi, I&apos;m Phoebe. Ask me anything about your onboarding documents and I&apos;ll answer
        with sources you can open.
      </p>
      <div className="flex flex-wrap justify-center gap-2">
        {SUGGESTED.map((q) => (
          <ThreadPrimitive.Suggestion
            key={q}
            prompt={q}
            send
            className="min-h-6 rounded-full border border-accent/30 bg-white px-3 py-1.5 text-sm text-accent hover:bg-accent/10 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {q}
          </ThreadPrimitive.Suggestion>
        ))}
      </div>
    </div>
  );
}

function AssistantBody({ message }: { message: ChatMessage }) {
  const viewer = useViewer();
  if (message.status === "error") {
    return (
      <p className="flex items-start gap-1.5 text-danger">
        <AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <span>{message.text}</span>
      </p>
    );
  }
  if (message.status === "streaming" && message.text === "") {
    return <p className="text-ink/70 motion-safe:animate-pulse">Phoebe is thinking…</p>;
  }
  const settled = message.status === "done";
  return (
    <>
      <CitedText
        text={message.text}
        citations={message.citations}
        settled={settled}
        onOpen={(c) => viewer.open(c.document_id, { start: c.start, end: c.end })}
      />
      {settled && !message.refused ? (
        <SourceList citations={message.citations} onOpen={viewer.open} />
      ) : null}
      {settled && message.refused ? (
        <ClosestList closest={message.closest} onOpen={(id) => viewer.open(id)} />
      ) : null}
    </>
  );
}

function MessageView({ id }: { id: string }) {
  const { messages } = useChat();
  const message = messages.find((m) => m.id === id);
  if (!message) return null;
  const user = message.role === "user";
  return (
    <MessagePrimitive.Root
      className={user ? "flex justify-end" : "flex justify-start gap-2"}
      data-role={message.role}
    >
      {user ? null : (
        <span className="mt-1 shrink-0">
          <Mascot size={28} />
        </span>
      )}
      <div
        className={
          user
            ? "max-w-[85%] rounded-2xl rounded-br-sm bg-accent px-3 py-2 text-sm whitespace-pre-wrap text-white"
            : "max-w-[85%] rounded-2xl rounded-bl-sm bg-white px-3 py-2 text-sm shadow-sm"
        }
      >
        {user ? message.text : <AssistantBody message={message} />}
      </div>
    </MessagePrimitive.Root>
  );
}

function Composer() {
  const { statusKnown, chatAvailable } = useChat();
  const noteId = useId();
  const paused = statusKnown && !chatAvailable;
  return (
    <div className="border-t border-ink/10 p-3">
      <ComposerPrimitive.Root className="flex items-end gap-2">
        <ComposerPrimitive.Input
          aria-label="Ask Phoebe a question"
          aria-describedby={paused ? noteId : undefined}
          placeholder="Ask about your onboarding…"
          submitMode="enter"
          // There is no stop control in this release; Escape must not silently cancel.
          cancelOnEscape={false}
          rows={1}
          disabled={!chatAvailable}
          className="min-h-10 flex-1 resize-none rounded-lg border border-ink/20 bg-white px-3 py-2 text-sm disabled:cursor-not-allowed disabled:bg-ink/5"
        />
        <ComposerPrimitive.Send
          aria-label="Send"
          className="inline-flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent text-white hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <SendHorizontal aria-hidden="true" className="size-4" />
        </ComposerPrimitive.Send>
      </ComposerPrimitive.Root>
      {paused ? (
        <p id={noteId} className="mt-2 flex items-start gap-1.5 text-xs text-ink/80">
          <Info aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
          <span>{PAUSED_COPY}</span>
        </p>
      ) : null}
    </div>
  );
}

function Thread() {
  const { announcement } = useChat();
  return (
    <ThreadPrimitive.Root className="flex h-full min-h-0 flex-col">
      {/* Scrollable, so it takes focus for keyboard scrolling. Not a live region. */}
      <ThreadPrimitive.Viewport
        role="region"
        aria-label="Conversation"
        tabIndex={0}
        className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3"
      >
        <ThreadPrimitive.Empty>
          <Greeting />
        </ThreadPrimitive.Empty>
        <ThreadPrimitive.Messages>
          {({ message }) => <MessageView id={message.id} />}
        </ThreadPrimitive.Messages>
      </ThreadPrimitive.Viewport>
      {/* The only live region: settled answers, once each — never per delta. */}
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>
      <Composer />
    </ThreadPrimitive.Root>
  );
}

/**
 * Cited, streaming chat. Needs a ChatRuntimeProvider (mounted per session by the
 * session gate) and a ViewerProvider above it.
 */
export function ChatPanel() {
  return <Thread />;
}
