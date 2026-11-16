import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Citation, DoneEvent, StatusOut, TurnOut } from "../api/types";
import { emitDemoReset } from "../state/demoReset";
import { OPEN, PAUSED } from "../test/fixtures";
import { makeClient } from "../test/render";
import { server } from "../test/server";
import { ChatPanel } from "./ChatPanel";
import { ChatRuntimeProvider } from "./ChatRuntimeProvider";

const viewer = vi.hoisted(() => ({ open: vi.fn(), close: vi.fn() }));
vi.mock("../documents/ViewerProvider", () => ({
  useViewer: () => viewer,
  ViewerProvider: ({ children }: { children: ReactNode }) => children,
}));

const SUGGESTED = [
  "How many PTO days do I get?",
  "What's on my first-week schedule?",
  "Who's who on the Platform team?",
  "How does on-call work?",
];

const PAUSED_COPY =
  "You can still browse Phoebe and explore the UX. Chat and document upload are paused until limits reset.";

const enc = new TextEncoder();

function frame(event: string, data: unknown): Uint8Array {
  return enc.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

function cite(n: number, over: Partial<Citation> = {}): Citation {
  return {
    n,
    chunk_id: `k${n}`,
    document_id: `d${n}`,
    document_title: `Doc ${n}`,
    heading_path: "Section",
    start: n * 10,
    end: n * 10 + 5,
    ...over,
  };
}

function done(over: Partial<DoneEvent> = {}): DoneEvent {
  return { text: "Answer.", refused: false, reason: null, citations: [], closest: [], ...over };
}

interface Chat {
  posts: unknown[];
  /** Pushes a frame to the open stream. */
  push(event: string, data: unknown): void;
  close(): void;
}

/** POST /api/chat answers with a stream the test drives frame by frame. */
function useChatStream(): Chat {
  const controllers: ReadableStreamDefaultController<Uint8Array>[] = [];
  const chat: Chat = {
    posts: [],
    push(event, data) {
      controllers.at(-1)?.enqueue(frame(event, data));
    },
    close() {
      controllers.at(-1)?.close();
    },
  };
  server.use(
    http.post("/api/chat", async ({ request }) => {
      chat.posts.push(await request.json());
      const body = new ReadableStream<Uint8Array>({
        start(c) {
          controllers.push(c);
        },
      });
      return new HttpResponse(body, { headers: { "Content-Type": "text/event-stream" } });
    }),
  );
  return chat;
}

/** POST /api/chat answers with a complete stream. */
function useChatAnswer(answer: DoneEvent, deltas: string[] = []): { posts: unknown[] } {
  const posts: unknown[] = [];
  server.use(
    http.post("/api/chat", async ({ request }) => {
      posts.push(await request.json());
      const body = new ReadableStream<Uint8Array>({
        start(c) {
          c.enqueue(frame("meta", { turn_id: "t1" }));
          for (const text of deltas) c.enqueue(frame("delta", { text }));
          c.enqueue(frame("done", answer));
          c.close();
        },
      });
      return new HttpResponse(body, { headers: { "Content-Type": "text/event-stream" } });
    }),
  );
  return { posts };
}

function useBackground(opts: { history?: TurnOut[]; status?: () => StatusOut } = {}) {
  const calls = { status: 0, history: 0 };
  server.use(
    http.get("/api/status", () => {
      calls.status += 1;
      return HttpResponse.json(opts.status ? opts.status() : OPEN);
    }),
    http.get("/api/chat/history", () => {
      calls.history += 1;
      return HttpResponse.json(opts.history ?? []);
    }),
  );
  return calls;
}

function renderPanel() {
  return render(
    <QueryClientProvider client={makeClient()}>
      <ChatRuntimeProvider>
        <ChatPanel />
      </ChatRuntimeProvider>
    </QueryClientProvider>,
  );
}

/** The message list, excluding the screen-reader live region. */
function convo() {
  return within(screen.getByRole("region", { name: "Conversation" }));
}

async function ask(user: ReturnType<typeof userEvent.setup>, question: string) {
  const input = await screen.findByRole("textbox", { name: "Ask Phoebe a question" });
  await waitFor(() => expect(input).toBeEnabled());
  await user.type(input, question);
  await user.keyboard("{Enter}");
}

beforeEach(() => {
  viewer.open.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ChatPanel", () => {
  it("shows mascot greeting and suggested questions", async () => {
    useBackground();
    const { posts } = useChatAnswer(done({ text: "You get 20 days." }));
    const user = userEvent.setup();
    renderPanel();

    expect(await screen.findByText(/I'm Phoebe/)).toBeInTheDocument();
    const buttons = await screen.findAllByRole("button", { name: /\?$/ });
    expect(buttons.map((b) => b.textContent)).toEqual(SUGGESTED);

    const first = screen.getByRole("button", { name: SUGGESTED[0] });
    await waitFor(() => expect(first).toBeEnabled());
    await user.click(first);
    expect(await convo().findByText("You get 20 days.")).toBeInTheDocument();
    expect(posts).toEqual([{ question: SUGGESTED[0] }]);
  });

  it("streams text then settles to done.text with numbered citation buttons [1] [2]", async () => {
    useBackground();
    const chat = useChatStream();
    const user = userEvent.setup();
    renderPanel();

    await ask(user, "How many PTO days?");
    chat.push("meta", { turn_id: "t1" });
    chat.push("delta", { text: "PTO is [P3]" });
    expect(await screen.findByText("PTO is [P3]")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Source/ })).not.toBeInTheDocument();

    chat.push(
      "done",
      done({
        text: "PTO is 20 days [1] and carries over [2].",
        citations: [cite(1, { document_title: "Handbook" }), cite(2, { document_title: "Leave" })],
      }),
    );
    chat.close();

    const one = await screen.findByRole("button", { name: "Source 1: Handbook" });
    const two = screen.getByRole("button", { name: "Source 2: Leave" });
    expect(one).toHaveTextContent("[1]");
    expect(two).toHaveTextContent("[2]");
    expect(screen.queryByText(/\[P3\]/)).not.toBeInTheDocument();
    expect(chat.posts).toEqual([{ question: "How many PTO days?" }]);
  });

  it("citation button opens the viewer at the passage", async () => {
    useBackground();
    useChatAnswer(
      done({
        text: "See [1].",
        citations: [
          cite(1, { document_id: "doc-9", document_title: "Handbook", start: 120, end: 180 }),
        ],
      }),
    );
    const user = userEvent.setup();
    renderPanel();

    await ask(user, "Where?");
    await user.click(await screen.findByRole("button", { name: "Source 1: Handbook" }));
    expect(viewer.open).toHaveBeenCalledWith("doc-9", { start: 120, end: 180 });
  });

  it("source list under each answer lists unique cited documents", async () => {
    useBackground();
    useChatAnswer(
      done({
        text: "A [1], B [2], C [3].",
        citations: [
          cite(1, { document_id: "h", document_title: "Handbook" }),
          cite(2, { document_id: "h", document_title: "Handbook", start: 99, end: 120 }),
          cite(3, { document_id: "r", document_title: "Runbook" }),
        ],
      }),
    );
    const user = userEvent.setup();
    renderPanel();

    await ask(user, "Q?");
    const sources = await screen.findByRole("list", { name: "Sources" });
    const items = within(sources).getAllByRole("listitem");
    expect(items.map((i) => i.textContent)).toEqual(["Handbook", "Runbook"]);
    await user.click(within(sources).getByRole("button", { name: "Runbook" }));
    expect(viewer.open).toHaveBeenCalledWith("r", { start: 30, end: 35 });
  });

  it('refused answer shows refusal text and "Closest documents" links that open the viewer', async () => {
    useBackground();
    useChatAnswer(
      done({
        text: "I couldn't find that in your documents.",
        refused: true,
        reason: "no_support",
        closest: [
          { document_id: "b1", title: "Benefits" },
          { document_id: "h1", title: "Handbook" },
        ],
      }),
      ["Something [P1]"],
    );
    const user = userEvent.setup();
    renderPanel();

    await ask(user, "Can I bring my dog?");
    expect(await convo().findByText("I couldn't find that in your documents.")).toBeInTheDocument();
    expect(screen.queryByText(/Something/)).not.toBeInTheDocument();
    const closest = screen.getByRole("list", { name: "Closest documents" });
    await user.click(within(closest).getByRole("button", { name: "Benefits" }));
    expect(viewer.open).toHaveBeenCalledWith("b1");
  });

  it('removed citation renders "source removed" and is not a button', async () => {
    useBackground({
      history: [
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
          text: "PTO is 20 days [1] and carries over [2].",
          refused: false,
          created_at: "2026-11-15T10:00:01Z",
          citations: [
            { ...cite(1, { document_title: "Handbook" }), removed: false },
            { ...cite(2, { document_title: "Old policy" }), removed: true },
          ],
        },
      ],
    });
    renderPanel();

    expect(await screen.findByRole("button", { name: "Source 1: Handbook" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Source 2/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Old policy/ })).not.toBeInTheDocument();
    expect(screen.getAllByText(/source removed/).length).toBeGreaterThan(0);
  });

  it("send is disabled while an answer is streaming", async () => {
    useBackground();
    const chat = useChatStream();
    const user = userEvent.setup();
    renderPanel();

    await ask(user, "First?");
    chat.push("delta", { text: "Working" });
    expect(await screen.findByText("Working")).toBeInTheDocument();

    const input = screen.getByRole("textbox", { name: "Ask Phoebe a question" });
    await user.type(input, "Second?");
    await user.keyboard("{Enter}");
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(chat.posts).toHaveLength(1);

    chat.push("done", done({ text: "Finished." }));
    chat.close();
    expect(await convo().findByText("Finished.")).toBeInTheDocument();
    expect(chat.posts).toEqual([{ question: "First?" }]);
  });

  it("503 chat_paused before stream: composer disabled, tooltip copy shown, status refetched", async () => {
    let paused = false;
    const calls = useBackground({ status: () => (paused ? PAUSED : OPEN) });
    server.use(
      http.post("/api/chat", () => {
        paused = true;
        return HttpResponse.json({ detail: "chat_paused" }, { status: 503 });
      }),
    );
    const user = userEvent.setup();
    renderPanel();

    expect(screen.queryByText(PAUSED_COPY)).not.toBeInTheDocument();
    await ask(user, "Hello?");
    const before = calls.status;
    expect(
      await convo().findByText("Rate limit exceeded. Please wait for sessions to refresh."),
    ).toBeInTheDocument();
    expect(await screen.findByText(PAUSED_COPY)).toBeInTheDocument();
    expect(calls.status).toBeGreaterThanOrEqual(Math.max(before, 2));
    const input = screen.getByRole("textbox", { name: "Ask Phoebe a question" });
    expect(input).toBeDisabled();
    expect(input).toHaveAccessibleDescription(PAUSED_COPY);
  });

  it("history loads from /api/chat/history on mount", async () => {
    const calls = useBackground({
      history: [
        {
          id: "u1",
          role: "user",
          text: "Earlier question?",
          refused: false,
          created_at: "2026-11-15T10:00:00Z",
          citations: [],
        },
        {
          id: "a1",
          role: "assistant",
          text: "Earlier answer.",
          refused: false,
          created_at: "2026-11-15T10:00:01Z",
          citations: [],
        },
      ],
    });
    renderPanel();

    expect(await screen.findByText("Earlier question?")).toBeInTheDocument();
    expect(screen.getByText("Earlier answer.")).toBeInTheDocument();
    expect(calls.history).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText(/I'm Phoebe/)).not.toBeInTheDocument();
  });

  it("screen reader: one polite live region announces the settled answer text once per answer, not each delta", async () => {
    useBackground();
    const chat = useChatStream();
    const user = userEvent.setup();
    renderPanel();

    const regions = await screen.findAllByRole("status");
    expect(regions).toHaveLength(1);
    const region = regions[0]!;
    expect(region).toHaveAttribute("aria-live", "polite");

    const seen: string[] = [];
    const observer = new MutationObserver(() => {
      const text = region.textContent ?? "";
      if (text && seen.at(-1) !== text) seen.push(text);
    });
    observer.observe(region, { childList: true, subtree: true, characterData: true });

    await ask(user, "PTO?");
    chat.push("delta", { text: "PTO " });
    chat.push("delta", { text: "is [P3]" });
    expect(await screen.findByText("PTO is [P3]")).toBeInTheDocument();
    expect(region).toHaveTextContent("");

    chat.push("done", done({ text: "PTO is 20 days [1].", citations: [cite(1)] }));
    chat.close();
    await waitFor(() => expect(region).toHaveTextContent("PTO is 20 days [1]."));
    await act(async () => {});
    observer.disconnect();
    expect(seen).toEqual(["PTO is 20 days [1]."]);
  });

  it("unmount aborts the in-flight stream", async () => {
    useBackground();
    const chat = useChatStream();
    const signals: AbortSignal[] = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      if (init?.signal) signals.push(init.signal);
      return realFetch(input, init);
    });
    const user = userEvent.setup();
    const { unmount } = renderPanel();

    await ask(user, "Long answer?");
    chat.push("delta", { text: "Still going" });
    expect(await screen.findByText("Still going")).toBeInTheDocument();
    expect(signals).toHaveLength(1);
    expect(signals[0]?.aborted).toBe(false);

    unmount();
    expect(signals[0]?.aborted).toBe(true);
  });

  it("Escape in the composer while streaming neither cancels the answer nor shows an error", async () => {
    useBackground();
    const chat = useChatStream();
    const signals: AbortSignal[] = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      if (init?.signal) signals.push(init.signal);
      return realFetch(input, init);
    });
    const user = userEvent.setup();
    renderPanel();

    await ask(user, "Long answer?");
    chat.push("delta", { text: "Still going" });
    expect(await screen.findByText("Still going")).toBeInTheDocument();

    await user.click(screen.getByRole("textbox", { name: "Ask Phoebe a question" }));
    await user.keyboard("{Escape}");
    expect(signals[0]?.aborted).toBe(false);
    expect(screen.queryByText(/Something went wrong/)).not.toBeInTheDocument();
    expect(screen.queryByText("You stopped this answer.")).not.toBeInTheDocument();

    chat.push("done", done({ text: "Finished." }));
    chat.close();
    expect(await convo().findByText("Finished.")).toBeInTheDocument();
    expect(screen.queryByText(/Something went wrong/)).not.toBeInTheDocument();
  });

  it("a question sent before history arrives still shows history first", async () => {
    let releaseHistory!: () => void;
    const historyGate = new Promise<void>((resolve) => {
      releaseHistory = resolve;
    });
    server.use(
      http.get("/api/status", () => HttpResponse.json(OPEN)),
      http.get("/api/chat/history", async () => {
        await historyGate;
        return HttpResponse.json([
          {
            id: "u1",
            role: "user",
            text: "Earlier question?",
            refused: false,
            created_at: "2026-11-15T10:00:00Z",
            citations: [],
          },
          {
            id: "a1",
            role: "assistant",
            text: "Earlier answer.",
            refused: false,
            created_at: "2026-11-15T10:00:01Z",
            citations: [],
          },
        ] satisfies TurnOut[]);
      }),
    );
    useChatAnswer(done({ text: "New answer." }));
    const user = userEvent.setup();
    renderPanel();

    await ask(user, "New question?");
    expect(await convo().findByText("New answer.")).toBeInTheDocument();

    releaseHistory();
    expect(await convo().findByText("Earlier question?")).toBeInTheDocument();
    const order = convo()
      .getAllByText(/^(Earlier question\?|Earlier answer\.|New question\?|New answer\.)$/)
      .map((el) => el.textContent);
    expect(order).toEqual(["Earlier question?", "Earlier answer.", "New question?", "New answer."]);
  });

  it("demo reset clears the conversation", async () => {
    useBackground();
    useChatAnswer(done({ text: "An answer." }));
    const user = userEvent.setup();
    renderPanel();

    await ask(user, "Question?");
    expect(await convo().findByText("An answer.")).toBeInTheDocument();
    act(() => emitDemoReset());
    expect(screen.queryByText("An answer.")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("");
    expect(await screen.findByText(/I'm Phoebe/)).toBeInTheDocument();
  });
});
