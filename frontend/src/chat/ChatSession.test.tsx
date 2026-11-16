import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { useSession } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server } from "../test/server";

const enc = new TextEncoder();

function frame(event: string, data: unknown): Uint8Array {
  return enc.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

/** POST /api/chat answers with a stream the test drives frame by frame. */
function useChatStream() {
  const controllers: ReadableStreamDefaultController<Uint8Array>[] = [];
  const chat = {
    posts: 0,
    push(event: string, data: unknown) {
      controllers.at(-1)?.enqueue(frame(event, data));
    },
    close() {
      controllers.at(-1)?.close();
    },
  };
  server.use(
    http.post("/api/chat", () => {
      chat.posts += 1;
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

function convo() {
  return within(screen.getByRole("region", { name: "Conversation" }));
}

describe("chat across the Employee/Admin toggle", () => {
  it("an answer streaming while the visitor visits Admin keeps streaming and completes", async () => {
    useSession();
    let historyCalls = 0;
    server.use(
      http.get("/api/chat/history", () => {
        historyCalls += 1;
        return HttpResponse.json([]);
      }),
    );
    const chat = useChatStream();
    const signals: AbortSignal[] = [];
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      if (init?.signal) signals.push(init.signal);
      return realFetch(input, init);
    });
    const user = userEvent.setup();
    const { router } = renderApp("/employee");

    const input = await screen.findByRole("textbox", { name: "Ask Phoebe a question" });
    await waitFor(() => expect(input).toBeEnabled());
    await user.type(input, "Long answer?");
    await user.keyboard("{Enter}");
    chat.push("delta", { text: "Half of it" });
    expect(await convo().findByText("Half of it")).toBeInTheDocument();

    await act(() => router.navigate("/admin/people"));
    expect(await screen.findByRole("heading", { name: "People & Progress" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Conversation" })).not.toBeInTheDocument();
    // The stream keeps going while Admin is showing.
    chat.push("delta", { text: " and more" });

    await act(() => router.navigate("/employee"));
    expect(await convo().findByText("Half of it and more")).toBeInTheDocument();
    expect(convo().getByText("Long answer?")).toBeInTheDocument();
    expect(signals.every((s) => !s.aborted)).toBe(true);

    chat.push("done", {
      text: "The whole answer.",
      refused: false,
      reason: null,
      citations: [],
      closest: [],
    });
    chat.close();
    expect(await convo().findByText("The whole answer.")).toBeInTheDocument();
    expect(screen.queryByText(/Something went wrong/)).not.toBeInTheDocument();
    expect(chat.posts).toBe(1);
    // History loads once per session, not again on each visit to the Employee view.
    expect(historyCalls).toBe(1);
    vi.restoreAllMocks();
  });
});
