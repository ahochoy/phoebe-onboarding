import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PersonProgress, TaskView } from "../api/types";
import { TasksPanel } from "../employee/TasksPanel";
import { makeTask, makeTasks, useSession } from "../test/fixtures";
import { makeClient } from "../test/render";
import { server } from "../test/server";
import { PeopleTab } from "./PeopleTab";

vi.mock("../lib/celebrate", () => ({ celebrate: vi.fn() }));

const PEOPLE: PersonProgress[] = [
  {
    person_id: "p1",
    name: "Alex Rivera",
    team_name: "Platform",
    department_name: "Engineering",
    start_date: "2026-11-10",
    done: 6,
    total: 14,
  },
  {
    person_id: "p2",
    name: "Dana Cho",
    team_name: "Brand",
    department_name: null,
    start_date: "2026-10-01",
    done: 3,
    total: 3,
  },
];

const DANA_TASKS: TaskView[] = [
  makeTask("c1", "company", { title: "Read handbook", done: true }),
  makeTask("t1", "team", { title: "Meet the team", done: false }),
];

function renderTab(client = makeClient()) {
  render(
    <QueryClientProvider client={client}>
      <PeopleTab />
    </QueryClientProvider>,
  );
  return client;
}

describe("PeopleTab", () => {
  beforeEach(() => {
    useSession();
    server.use(
      http.get("/api/people", () => HttpResponse.json(PEOPLE)),
      http.get("/api/people/:id/tasks", ({ params }) =>
        HttpResponse.json(params["id"] === "p2" ? DANA_TASKS : []),
      ),
    );
  });

  it("people table: name, department › team, start date, progress bar, 'done of total'", async () => {
    renderTab();
    const table = await screen.findByRole("table", { name: "People and onboarding progress" });
    const headers = within(table).getAllByRole("columnheader");
    expect(headers.map((h) => h.textContent)).toEqual([
      "Name",
      "Department › Team",
      "Start date",
      "Progress",
    ]);
    for (const h of headers) expect(h).toHaveAttribute("scope", "col");

    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3); // header + 2 people
    const alex = within(rows[1]!);
    expect(alex.getByRole("button", { name: "Alex Rivera" })).toBeInTheDocument();
    expect(alex.getByText("Engineering › Platform")).toBeInTheDocument();
    expect(alex.getByText("Nov 10, 2026")).toBeInTheDocument();
    const bar = alex.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "6");
    expect(bar).toHaveAttribute("aria-valuemax", "14");
    expect(alex.getByText("6 of 14 done")).toBeInTheDocument();

    // No department: team alone, no stray separator.
    expect(within(rows[2]!).getByText("Brand")).toBeInTheDocument();
  });

  it("clicking a row shows that person's checklist by tier, read-only", async () => {
    const user = userEvent.setup();
    renderTab();
    const row = (await screen.findByRole("button", { name: "Dana Cho" })).closest("tr")!;
    await user.click(row);

    const region = await screen.findByRole("region", { name: "Dana Cho's checklist" });
    expect(within(region).getByText("Company")).toBeInTheDocument();
    expect(within(region).getByText("Platform", { selector: "h4" })).toBeInTheDocument();
    const done = within(region).getByText("Read handbook").closest("li")!;
    expect(within(done).getByText("Done")).toBeInTheDocument();
    const notDone = within(region).getByText("Meet the team").closest("li")!;
    expect(within(notDone).getByText("Not done")).toBeInTheDocument();
    // Read-only: nothing to check.
    expect(within(region).queryByRole("checkbox")).not.toBeInTheDocument();
    expect(within(region).queryByRole("button")).not.toBeInTheDocument();
  });

  it("Enter on a row's button shows the checklist", async () => {
    const user = userEvent.setup();
    renderTab();
    const button = await screen.findByRole("button", { name: "Dana Cho" });
    button.focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("region", { name: "Dana Cho's checklist" })).toBeInTheDocument();
    expect(button).toHaveAttribute("aria-pressed", "true");
  });

  it("shows an error message when the list cannot load", async () => {
    server.use(
      http.get("/api/people", () =>
        HttpResponse.json({ detail: "internal_error" }, { status: 500 }),
      ),
    );
    renderTab();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Something went wrong on our side. Try again in a moment.",
    );
  });

  it("Alex's row reflects completions made in employee mode", async () => {
    const user = userEvent.setup();
    const alexTasks = makeTasks();
    server.use(
      http.get("/api/tasks", () => HttpResponse.json(alexTasks)),
      http.get("/api/people", () =>
        HttpResponse.json([
          {
            ...PEOPLE[0],
            done: alexTasks.filter((t) => t.done).length,
            total: alexTasks.length,
          },
        ]),
      ),
      http.put("/api/tasks/:id/completion", async ({ params, request }) => {
        const body = (await request.json()) as { done: boolean };
        const task = alexTasks.find((t) => t.id === params["id"]);
        if (task) task.done = body.done;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    // Both views share one cache, as in the app.
    const client = makeClient();
    render(
      <QueryClientProvider client={client}>
        <TasksPanel />
        <PeopleTab />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("6 of 14 done", { selector: "td *, td" })).toBeInTheDocument();

    const box = await screen.findByRole("checkbox", { name: "Task company-3" });
    await user.click(box);

    await waitFor(() =>
      expect(screen.getByText("7 of 14 done", { selector: "td *, td" })).toBeInTheDocument(),
    );
  });
});
