import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import type { TaskView } from "../api/types";
import { messageFor } from "../lib/messages";
import { makeClient } from "../test/render";
import { makeTask, makeTasks } from "../test/fixtures";
import { server } from "../test/server";
import { celebrate } from "../lib/celebrate";
import { TasksPanel } from "./TasksPanel";

vi.mock("../lib/celebrate", () => ({ celebrate: vi.fn() }));

interface PutRecord {
  id: string;
  done: boolean;
}

/** Serves GET /api/tasks and records PUT completions, tracking concurrency. */
function useTasksApi(tasks: TaskView[], opts: { putDelayMs?: number; putStatus?: number } = {}) {
  const state = {
    tasks: tasks.map((t) => ({ ...t })),
    puts: [] as PutRecord[],
    inFlight: 0,
    maxInFlight: 0,
  };
  server.use(
    http.get("/api/tasks", () => HttpResponse.json(state.tasks)),
    http.put("/api/tasks/:id/completion", async ({ params, request }) => {
      state.inFlight += 1;
      state.maxInFlight = Math.max(state.maxInFlight, state.inFlight);
      const body = (await request.json()) as { done: boolean };
      const id = String(params["id"]);
      state.puts.push({ id, done: body.done });
      if (opts.putDelayMs) await delay(opts.putDelayMs);
      state.inFlight -= 1;
      if (opts.putStatus) {
        return HttpResponse.json({ detail: "internal_error" }, { status: opts.putStatus });
      }
      const task = state.tasks.find((t) => t.id === id);
      if (task) task.done = body.done;
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return state;
}

function renderPanel() {
  const client = makeClient();
  render(
    <QueryClientProvider client={client}>
      <TasksPanel />
    </QueryClientProvider>,
  );
  return client;
}

beforeEach(() => vi.mocked(celebrate).mockClear());

describe("TasksPanel", () => {
  it('reads "6 of 14 done" with progressbar semantics', async () => {
    useTasksApi(makeTasks());
    renderPanel();
    expect(await screen.findByText("6 of 14 done")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "6");
    expect(bar).toHaveAttribute("aria-valuemax", "14");
  });

  it("shows a Radix accordion per tier, titled by tier, all open", async () => {
    useTasksApi(makeTasks());
    renderPanel();
    for (const title of ["Company", "Engineering", "Platform"]) {
      const trigger = await screen.findByRole("button", { name: title });
      expect(trigger).toHaveAttribute("aria-expanded", "true");
    }
    const company = screen.getByRole("region", { name: "Company" });
    expect(within(company).getAllByRole("checkbox")).toHaveLength(4);
  });

  it("checking a task PUTs the completion and updates the count immediately", async () => {
    const api = useTasksApi(makeTasks(), { putDelayMs: 50 });
    renderPanel();
    const box = await screen.findByRole("checkbox", { name: /Task company-3/ });
    await userEvent.click(box);
    // Optimistic: the count moves before the PUT has settled.
    expect(screen.getByText("7 of 14 done")).toBeInTheDocument();
    expect(box).toBeChecked();
    await waitFor(() => expect(api.puts).toEqual([{ id: "company-3", done: true }]));
    await waitFor(() => expect(api.inFlight).toBe(0));
  });

  it("rapid toggles end in the server's state with at most one request in flight per task", async () => {
    const api = useTasksApi(makeTasks(), { putDelayMs: 30 });
    renderPanel();
    const box = await screen.findByRole("checkbox", { name: /Task company-3/ });
    for (let i = 0; i < 5; i++) await userEvent.click(box);
    // Five clicks from unchecked leave it checked.
    expect(box).toBeChecked();
    await waitFor(() => expect(api.puts.length).toBeGreaterThan(0));
    await waitFor(() => expect(api.inFlight).toBe(0));
    await delay(80);
    expect(api.maxInFlight).toBeLessThanOrEqual(1);
    const last = api.puts[api.puts.length - 1];
    expect(last?.done).toBe(true);
    expect(api.tasks.find((t) => t.id === "company-3")?.done).toBe(true);
    expect(box).toBeChecked();
    expect(screen.getByText("7 of 14 done")).toBeInTheDocument();
  });

  it("sends the latest wanted state after an in-flight request settles", async () => {
    const api = useTasksApi(makeTasks(), { putDelayMs: 60 });
    renderPanel();
    const box = await screen.findByRole("checkbox", { name: /Task company-3/ });
    await userEvent.click(box); // true, goes out
    await userEvent.click(box); // false, queued
    await waitFor(() => expect(api.puts.map((p) => p.done)).toEqual([true, false]));
    await waitFor(() => expect(api.inFlight).toBe(0));
    expect(api.maxInFlight).toBe(1);
    await waitFor(() => expect(box).not.toBeChecked());
  });

  it("rolls back a failed toggle and shows messageFor(err)", async () => {
    useTasksApi(makeTasks(), { putStatus: 500 });
    renderPanel();
    const box = await screen.findByRole("checkbox", { name: /Task company-3/ });
    await userEvent.click(box);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(messageFor(new ApiError(500, "internal_error")));
    await waitFor(() => expect(box).not.toBeChecked());
    expect(screen.getByText("6 of 14 done")).toBeInTheDocument();
  });

  it("calls celebrate once when the last task of a tier is completed", async () => {
    const tasks = [
      makeTask("c1", "company", { done: true }),
      makeTask("t1", "team", { done: true }),
      makeTask("t2", "team", { done: false }),
      makeTask("t3", "team", { done: false }),
    ];
    useTasksApi(tasks);
    renderPanel();
    await userEvent.click(await screen.findByRole("checkbox", { name: /Task t2/ }));
    expect(celebrate).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("checkbox", { name: /Task t3/ }));
    expect(celebrate).toHaveBeenCalledTimes(1);
  });

  it('shows the "All done!" badge at 100%', async () => {
    useTasksApi([makeTask("a", "company", { done: true }), makeTask("b", "team", { done: false })]);
    renderPanel();
    expect(screen.queryByText("All done!")).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole("checkbox", { name: /Task b/ }));
    expect(screen.getByText("All done!")).toBeInTheDocument();
    expect(screen.getByText("2 of 2 done")).toBeInTheDocument();
  });

  it('renders a task link as an external link with rel="noopener noreferrer"', async () => {
    useTasksApi([makeTask("a", "company", { link: "https://example.com/handbook" })]);
    renderPanel();
    const link = await screen.findByRole("link", { name: /Task a/ });
    expect(link).toHaveAttribute("href", "https://example.com/handbook");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("does not render links with unsafe schemes", async () => {
    useTasksApi([makeTask("a", "company", { link: "javascript:alert(1)" })]);
    renderPanel();
    await screen.findByRole("checkbox", { name: /Task a/ });
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows messageFor(err) when tasks fail to load", async () => {
    server.use(
      http.get("/api/tasks", () =>
        HttpResponse.json({ detail: "internal_error" }, { status: 500 }),
      ),
    );
    renderPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      messageFor(new ApiError(500, "internal_error")),
    );
  });
});
