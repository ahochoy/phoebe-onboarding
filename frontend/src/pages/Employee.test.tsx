import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LG_UP } from "../lib/useMediaQuery";
import { useSession } from "../test/fixtures";
import { makeClient, renderApp } from "../test/render";
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
const listeners = new Set<() => void>();
let isWide = false;

function setWide(wide: boolean) {
  isWide = wide;
  window.matchMedia = ((query: string) => ({
    get matches() {
      return query === LG_UP ? isWide : false;
    },
    media: query,
    onchange: null,
    addEventListener: (_: string, l: () => void) => {
      listeners.add(l);
    },
    removeEventListener: (_: string, l: () => void) => {
      listeners.delete(l);
    },
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
  act(() => listeners.forEach((l) => l()));
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

  it("desktop (>=1024px) shows Tasks | Chat | Documents as three labelled regions", async () => {
    setWide(true);
    renderEmployee();
    expect(await screen.findByRole("region", { name: "Tasks" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Chat" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Documents" })).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    // The columns are not tab panels, so they are not tab stops either.
    expect(document.querySelectorAll("[role=presentation][tabindex]")).toHaveLength(0);
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

  it("crossing the breakpoint keeps chat state (panels are not remounted)", async () => {
    setWide(false);
    const user = userEvent.setup();
    renderEmployee();
    await user.type(await screen.findByLabelText("Ask Phoebe a question"), "hello");
    setWide(true);
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Ask Phoebe a question")).toHaveValue("hello");
    setWide(false);
    expect(screen.getByLabelText("Ask Phoebe a question")).toHaveValue("hello");
  });

  it("the profile card shows Day N and start date; the people list shows manager and buddy", async () => {
    setWide(true);
    renderEmployee();
    const card = await screen.findByRole("group", { name: "About you" });
    expect(within(card).getByText("Melinda Grant")).toBeInTheDocument();
    expect(within(card).getByText("Jordan Moore")).toBeInTheDocument();
    expect(screen.getByText("Day 5 · Started Nov 10, 2026")).toBeInTheDocument();
  });

  it("desktop uses the wider page and roomier sidebar columns", async () => {
    setWide(true);
    renderApp("/employee");
    const chat = await screen.findByRole("region", { name: "Chat" });
    expect(screen.getByRole("main")).toHaveClass("max-w-[120rem]");
    expect(screen.getByRole("banner").firstElementChild).toHaveClass("max-w-[120rem]");
    const grid = chat.closest('[class*="lg:grid-cols-"]');
    expect(grid).toHaveClass("lg:grid-cols-[30rem_minmax(0,1fr)_20rem]", "lg:gap-6");
  });
});
