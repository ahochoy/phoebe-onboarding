import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MD_UP } from "../lib/useMediaQuery";
import { useSession } from "../test/fixtures";
import { makeClient } from "../test/render";
import { Employee } from "./Employee";

vi.mock("../employee/TasksPanel", () => ({
  TasksPanel: () => (
    <section aria-labelledby="tasks-heading">
      <h2 id="tasks-heading">Tasks</h2>
    </section>
  ),
}));
vi.mock("../documents/DocumentsPanel", () => ({
  DocumentsPanel: () => <p>docs list</p>,
}));
vi.mock("../chat/ChatPanel", () => ({
  ChatPanel: function FakeChat() {
    const [text, setText] = useState("");
    return (
      <input
        aria-label="Ask Phoebe a question"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
    );
  },
}));
vi.mock("../documents/ViewerProvider", () => ({
  ViewerProvider: ({ children }: { children: ReactNode }) => children,
}));

const realMatchMedia = window.matchMedia;

function setWide(wide: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: query === MD_UP ? wide : false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}

function renderEmployee() {
  return render(
    <QueryClientProvider client={makeClient()}>
      <Employee />
    </QueryClientProvider>,
  );
}

describe("Employee page", () => {
  beforeEach(() => {
    useSession();
  });
  afterEach(() => {
    window.matchMedia = realMatchMedia;
  });

  it("desktop (>=768px) shows Tasks | Chat | Documents as three labelled regions", async () => {
    setWide(true);
    renderEmployee();
    expect(await screen.findByRole("region", { name: "Tasks" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Chat" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Documents" })).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });

  it("mobile shows one panel with bottom tabs Tasks | Chat | Docs, Chat selected by default", async () => {
    setWide(false);
    const user = userEvent.setup();
    renderEmployee();
    const tabs = within(await screen.findByRole("tablist"));
    expect(tabs.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Tasks", "Chat", "Docs"]);
    expect(tabs.getByRole("tab", { name: "Chat" })).toHaveAttribute("aria-selected", "true");

    // Chat state survives switching away and back: panels stay mounted.
    await user.type(screen.getByLabelText("Ask Phoebe a question"), "hello");
    await user.click(tabs.getByRole("tab", { name: "Docs" }));
    expect(tabs.getByRole("tab", { name: "Docs" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("docs list")).toBeVisible();
    await user.click(tabs.getByRole("tab", { name: "Chat" }));
    expect(screen.getByLabelText("Ask Phoebe a question")).toHaveValue("hello");
  });

  it("persona card shows start date, manager, buddy and Day N", async () => {
    setWide(true);
    renderEmployee();
    const card = await screen.findByRole("group", { name: "About you" });
    expect(within(card).getByText("Nov 10, 2026")).toBeInTheDocument();
    expect(within(card).getByText("Sam Lee")).toBeInTheDocument();
    expect(within(card).getByText("Jo Park")).toBeInTheDocument();
    expect(within(card).getByText("Day 5")).toBeInTheDocument();
  });
});
