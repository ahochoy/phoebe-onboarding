import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import type { ChatStreamEvent } from "../api/sse";
import { emitDemoReset } from "../state/demoReset";
import { OPEN } from "../test/fixtures";
import { makeClient } from "../test/render";
import { server } from "../test/server";
import { ChatPanel } from "./ChatPanel";
import { ChatRuntimeProvider } from "./ChatRuntimeProvider";

vi.mock("../documents/ViewerProvider", () => ({
  useViewer: () => ({ open: vi.fn(), close: vi.fn() }),
  ViewerProvider: ({ children }: { children: ReactNode }) => children,
}));

/**
 * A stream that ignores its abort signal, like frames already sitting in the
 * response buffer when the visitor resets: whatever is pushed is still yielded.
 */
const stream = vi.hoisted(() => {
  const state = {
    queue: [] as ChatStreamEvent[],
    wake: null as (() => void) | null,
    push(...events: ChatStreamEvent[]) {
      state.queue.push(...events);
      state.wake?.();
    },
  };
  return state;
});

vi.mock("../api/sse", () => ({
  async *streamChat(): AsyncGenerator<ChatStreamEvent> {
    for (;;) {
      const next = stream.queue.shift();
      if (next) {
        yield next;
        continue;
      }
      await new Promise<void>((resolve) => {
        stream.wake = resolve;
      });
    }
  },
}));

function renderPanel() {
  server.use(
    http.get("/api/status", () => HttpResponse.json(OPEN)),
    http.get("/api/chat/history", () => HttpResponse.json([])),
  );
  return render(
    <QueryClientProvider client={makeClient()}>
      <ChatRuntimeProvider>
        <ChatPanel />
      </ChatRuntimeProvider>
    </QueryClientProvider>,
  );
}

describe("ChatRuntimeProvider", () => {
  it("frames buffered after a demo reset are neither shown nor announced", async () => {
    stream.queue.length = 0;
    const user = userEvent.setup();
    renderPanel();

    const input = await screen.findByRole("textbox", { name: "Ask Phoebe a question" });
    await waitFor(() => expect(input).toBeEnabled());
    await user.type(input, "Question?");
    await user.keyboard("{Enter}");
    act(() => stream.push({ type: "delta", text: "Partial" }));
    expect(await screen.findByText("Partial")).toBeInTheDocument();

    act(() => emitDemoReset());
    expect(screen.queryByText("Partial")).not.toBeInTheDocument();

    await act(async () => {
      stream.push(
        { type: "delta", text: " more" },
        {
          type: "done",
          done: { text: "Late answer.", refused: false, reason: null, citations: [], closest: [] },
        },
      );
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.queryByText(/Late answer/)).not.toBeInTheDocument();
    expect(screen.queryByText(/more/)).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("");
    const convo = within(screen.getByRole("region", { name: "Conversation" }));
    expect(convo.getByText(/I'm Phoebe/)).toBeInTheDocument();
  });
});
