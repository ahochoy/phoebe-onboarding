import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import type { GroupNode } from "../api/types";
import { useTasks } from "../employee/useTasks";
import { makeDoc, makeTask, useSession } from "../test/fixtures";
import { makeClient } from "../test/render";
import { server } from "../test/server";
import { GroupsTab } from "./GroupsTab";

const TREE: GroupNode[] = [
  {
    id: "c1",
    kind: "company",
    name: "Acme Corp",
    owned: false,
    parent_id: null,
    children: [
      {
        id: "d1",
        kind: "department",
        name: "Engineering",
        owned: false,
        parent_id: "c1",
        children: [
          { id: "t1", kind: "team", name: "Platform", owned: true, parent_id: "d1", children: [] },
        ],
      },
      { id: "d2", kind: "department", name: "Sales", owned: true, parent_id: "c1", children: [] },
    ],
  },
];

const DOCS = [
  makeDoc("a", "company", { title: "Handbook", group_id: "c1", group_name: "Acme Corp" }),
  makeDoc("b", "team", { title: "Runbook", group_id: "t1", group_name: "Platform" }),
  makeDoc("c", "team", { title: "On-call guide", group_id: "t1", group_name: "Platform" }),
];

const TASKS = [
  makeTask("x", "company", { title: "Sign handbook", group_id: "c1", group_name: "Acme Corp" }),
  makeTask("y", "team", { title: "Set up laptop", group_id: "t1", group_name: "Platform" }),
];

function MineProbe() {
  useTasks("mine");
  return null;
}

function renderTab() {
  const client = makeClient();
  render(
    <QueryClientProvider client={client}>
      <MineProbe />
      <GroupsTab />
    </QueryClientProvider>,
  );
  return client;
}

function node(name: string) {
  return screen.getByRole("button", { name: new RegExp(`^${name}\\b`) }).closest("li")!;
}

describe("GroupsTab", () => {
  beforeEach(() => {
    useSession();
    server.use(
      http.get("/api/groups", () => HttpResponse.json(TREE)),
      http.get("/api/documents", () => HttpResponse.json(DOCS)),
      http.get("/api/tasks", () => HttpResponse.json(TASKS)),
    );
  });

  it("groups tree shows company → departments → teams with document and task counts", async () => {
    renderTab();
    await screen.findByRole("button", { name: /^Acme Corp/ });
    const root = screen.getByRole("list", { name: "Groups" });
    const items = within(root).getAllByRole("listitem");
    const names = items.map((li) => within(li).getAllByRole("button")[0]!.textContent);
    expect(names.map((n) => n!.split(/\d/)[0]!.trim())).toEqual([
      "Acme Corp",
      "Engineering",
      "Platform",
      "Sales",
    ]);
    expect(screen.getByRole("button", { name: /^Acme Corp/ })).toHaveAccessibleName(
      "Acme Corp, 1 document, 1 task",
    );
    expect(screen.getByRole("button", { name: /^Platform/ })).toHaveAccessibleName(
      "Platform, 2 documents, 1 task",
    );
    expect(screen.getByRole("button", { name: /^Sales/ })).toHaveAccessibleName(
      "Sales, 0 documents, 0 tasks",
    );
  });

  it("selecting a group lists the titles of its documents and tasks", async () => {
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: /^Platform/ }));
    const panel = screen.getByRole("region", { name: "Platform contents" });
    expect(within(panel).getByText("Runbook")).toBeInTheDocument();
    expect(within(panel).getByText("On-call guide")).toBeInTheDocument();
    expect(within(panel).getByText("Set up laptop")).toBeInTheDocument();
    expect(within(panel).queryByText("Handbook")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Platform/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(screen.getByRole("button", { name: /^Sales/ }));
    const empty = screen.getByRole("region", { name: "Sales contents" });
    expect(within(empty).getByText("No documents.")).toBeInTheDocument();
    expect(within(empty).getByText("No tasks.")).toBeInTheDocument();
  });

  it("add department under company; add team under a department", async () => {
    const bodies: unknown[] = [];
    server.use(
      http.post("/api/groups", async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json({ id: "n" }, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderTab();
    await screen.findByRole("button", { name: /^Acme Corp/ });
    // Only company can take departments; only departments can take teams.
    expect(screen.queryByRole("button", { name: "Add team to Platform" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Add department to Engineering" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add department to Acme Corp" }));
    let dialog = await screen.findByRole("dialog", { name: "Add department" });
    await user.type(within(dialog).getByRole("textbox", { name: /Name/ }), "Finance");
    await user.click(within(dialog).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toEqual({ name: "Finance", kind: "department", parent_id: "c1" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Add team to Engineering" }));
    dialog = await screen.findByRole("dialog", { name: "Add team" });
    await user.type(within(dialog).getByRole("textbox", { name: /Name/ }), "Data");
    await user.click(within(dialog).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toEqual({ name: "Data", kind: "team", parent_id: "d1" });
  });

  it("requires a name", async () => {
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Add department to Acme Corp" }));
    const dialog = await screen.findByRole("dialog", { name: "Add department" });
    await user.click(within(dialog).getByRole("button", { name: "Add" }));
    const name = within(dialog).getByRole("textbox", { name: /Name/ });
    expect(await within(dialog).findByText("Enter a name.")).toBeInTheDocument();
    expect(name).toHaveAccessibleDescription("Enter a name.");
  });

  it("rename PATCHes the name and refreshes groups, tasks and documents", async () => {
    let body: unknown;
    let url = "";
    let groupsGets = 0;
    server.use(
      http.get("/api/groups", () => {
        groupsGets += 1;
        return HttpResponse.json(TREE);
      }),
      http.patch("/api/groups/:id", async ({ request }) => {
        url = new URL(request.url).pathname;
        body = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Rename Platform" }));
    const dialog = await screen.findByRole("dialog", { name: "Rename group" });
    const name = within(dialog).getByRole("textbox", { name: /Name/ });
    expect(name).toHaveValue("Platform");
    await user.clear(name);
    await user.type(name, "Core Platform");
    const before = groupsGets;
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(body).toBeDefined());
    expect(url).toBe("/api/groups/t1");
    expect(body).toEqual({ name: "Core Platform" });
    await waitFor(() => expect(groupsGets).toBeGreaterThan(before));
  });

  it("delete confirms, then DELETEs", async () => {
    let deleted = "";
    server.use(
      http.delete("/api/groups/:id", ({ params }) => {
        deleted = String(params.id);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Delete Sales" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(deleted).toBe("");
    await user.click(within(dialog).getByRole("button", { name: "Yes, delete" }));
    await waitFor(() => expect(deleted).toBe("d2"));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("the company has no delete button", async () => {
    renderTab();
    await screen.findByRole("button", { name: /^Acme Corp/ });
    expect(screen.queryByRole("button", { name: "Delete Acme Corp" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rename Acme Corp" })).toBeInTheDocument();
  });

  it('delete in-use group shows "Move or delete its documents, tasks and teams first."', async () => {
    server.use(
      http.delete("/api/groups/:id", () =>
        HttpResponse.json({ detail: "group_in_use" }, { status: 409 }),
      ),
    );
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Delete Engineering" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Yes, delete" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Move or delete its documents, tasks and teams first.",
    );
    expect(dialog).toBeInTheDocument();
  });

  it("admin changes invalidate employee queries", async () => {
    let mine = 0;
    server.use(
      http.get("/api/tasks", ({ request }) => {
        if (new URL(request.url).searchParams.get("scope") === "mine") mine += 1;
        return HttpResponse.json(TASKS);
      }),
      http.post("/api/groups", () => HttpResponse.json({ id: "n" }, { status: 201 })),
    );
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Add department to Acme Corp" }));
    const dialog = await screen.findByRole("dialog", { name: "Add department" });
    await user.type(within(dialog).getByRole("textbox", { name: /Name/ }), "Ops");
    await waitFor(() => expect(mine).toBe(1));
    await user.click(within(dialog).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(mine).toBe(2));
    expect(node("Acme Corp")).toBeInTheDocument();
  });
});
