import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import type { GroupNode, TaskView } from "../api/types";
import { useTasks } from "../employee/useTasks";
import { makeTask, useSession } from "../test/fixtures";
import { makeClient } from "../test/render";
import { server } from "../test/server";
import { TasksTab } from "./TasksTab";

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
          { id: "t1", kind: "team", name: "Platform", owned: false, parent_id: "d1", children: [] },
        ],
      },
    ],
  },
];

function tasks(): TaskView[] {
  return [
    makeTask("a1", "company", {
      title: "Sign handbook",
      description: "Read and sign",
      group_id: "c1",
      group_name: "Acme Corp",
      position: 1,
    }),
    makeTask("a2", "company", {
      title: "Meet buddy",
      description: "Say hello",
      link: "https://example.com/buddy",
      group_id: "c1",
      group_name: "Acme Corp",
      position: 2,
    }),
    makeTask("p1", "team", {
      title: "Set up laptop",
      description: "",
      group_id: "t1",
      group_name: "Platform",
      position: 1,
    }),
    makeTask("p2", "team", {
      title: "Ship first PR",
      description: "Small one",
      group_id: "t1",
      group_name: "Platform",
      position: 2,
    }),
    makeTask("p3", "team", {
      title: "Join on-call",
      description: "Shadow",
      group_id: "t1",
      group_name: "Platform",
      position: 3,
    }),
  ];
}

function MineProbe() {
  useTasks("mine");
  return null;
}

function renderTab(client = makeClient()) {
  render(
    <QueryClientProvider client={client}>
      <MineProbe />
      <TasksTab />
    </QueryClientProvider>,
  );
  return client;
}

function mockList(list: TaskView[] = tasks()) {
  const calls = { all: 0, mine: 0 };
  server.use(
    http.get("/api/tasks", ({ request }) => {
      if (new URL(request.url).searchParams.get("scope") === "all") calls.all += 1;
      else calls.mine += 1;
      return HttpResponse.json(list);
    }),
  );
  return calls;
}

async function pickGroup(
  user: ReturnType<typeof userEvent.setup>,
  dialog: HTMLElement,
  name: string,
) {
  await user.click(within(dialog).getByRole("combobox", { name: "Group" }));
  await user.click(await screen.findByRole("option", { name }));
}

describe("TasksTab", () => {
  beforeEach(() => {
    useSession();
    server.use(http.get("/api/groups", () => HttpResponse.json(TREE)));
  });

  it("tasks listed by group (scope=all) with title, description, link", async () => {
    mockList();
    renderTab();
    const platform = await screen.findByRole("region", { name: "Platform" });
    expect(
      within(platform)
        .getAllByRole("listitem")
        .map((li) => within(li).getByRole("heading").textContent),
    ).toEqual(["Set up laptop", "Ship first PR", "Join on-call"]);
    expect(within(platform).getByText("Small one")).toBeInTheDocument();

    const company = screen.getByRole("region", { name: "Acme Corp" });
    expect(within(company).getByText("Read and sign")).toBeInTheDocument();
    const link = within(company).getByRole("link", { name: /example\.com\/buddy/ });
    expect(link).toHaveAttribute("href", "https://example.com/buddy");
  });

  it("create posts NewTask last in its group and invalidates employee queries", async () => {
    const calls = mockList();
    let body: unknown;
    server.use(
      http.post("/api/tasks", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ id: "n" }, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Add task" }));
    const dialog = await screen.findByRole("dialog", { name: "Add task" });
    await user.type(within(dialog).getByRole("textbox", { name: /Title/ }), "Read the wiki");
    await user.type(within(dialog).getByRole("textbox", { name: /Description/ }), "Start here");
    await user.type(within(dialog).getByRole("textbox", { name: /Link/ }), "https://wiki.example");
    await pickGroup(user, dialog, "Platform");
    const mineBefore = calls.mine;
    await user.click(within(dialog).getByRole("button", { name: "Add" }));

    await waitFor(() => expect(body).toBeDefined());
    expect(body).toEqual({
      title: "Read the wiki",
      description: "Start here",
      link: "https://wiki.example",
      group_id: "t1",
      position: 4,
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // admin changes invalidate the employee ["tasks","mine"] query
    await waitFor(() => expect(calls.mine).toBeGreaterThan(mineBefore));
  });

  it("create with empty link sends null and requires title and group", async () => {
    mockList();
    let body: unknown;
    server.use(
      http.post("/api/tasks", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ id: "n" }, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Add task" }));
    const dialog = await screen.findByRole("dialog", { name: "Add task" });
    await user.click(within(dialog).getByRole("button", { name: "Add" }));
    expect(await within(dialog).findByText("Enter a title.")).toBeInTheDocument();
    expect(within(dialog).getByText("Choose a group.")).toBeInTheDocument();
    expect(body).toBeUndefined();

    await user.type(within(dialog).getByRole("textbox", { name: /Title/ }), "Solo");
    await pickGroup(user, dialog, "Engineering");
    await user.click(within(dialog).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(body).toBeDefined());
    expect(body).toEqual({
      title: "Solo",
      description: "",
      link: null,
      group_id: "d1",
      position: 1,
    });
  });

  it("shows messageFor copy when the server rejects the link", async () => {
    mockList();
    server.use(
      http.post("/api/tasks", () =>
        HttpResponse.json({ detail: "invalid_request" }, { status: 422 }),
      ),
    );
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Add task" }));
    const dialog = await screen.findByRole("dialog", { name: "Add task" });
    await user.type(within(dialog).getByRole("textbox", { name: /Title/ }), "X");
    await user.type(within(dialog).getByRole("textbox", { name: /Link/ }), "http://insecure");
    await pickGroup(user, dialog, "Platform");
    await user.click(within(dialog).getByRole("button", { name: "Add" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Some of the information entered is not valid. Check it and try again.",
    );
    expect(dialog).toBeInTheDocument();
  });

  it("edit PATCHes changed fields only", async () => {
    mockList();
    let body: unknown;
    let url = "";
    server.use(
      http.patch("/api/tasks/:id", async ({ request }) => {
        url = new URL(request.url).pathname;
        body = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Edit Sign handbook" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit task" });
    const title = within(dialog).getByRole("textbox", { name: /Title/ });
    await user.clear(title);
    await user.type(title, "Sign the handbook");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(body).toBeDefined());
    expect(url).toBe("/api/tasks/a1");
    expect(body).toEqual({ title: "Sign the handbook" });
  });

  it('removing a link sends {"link": null}', async () => {
    mockList();
    let body: unknown;
    server.use(
      http.patch("/api/tasks/:id", async ({ request }) => {
        body = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Edit Meet buddy" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit task" });
    await user.clear(within(dialog).getByRole("textbox", { name: /Link/ }));
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(body).toBeDefined());
    expect(body).toEqual({ link: null });
  });

  it("clearing the description sends an empty string, never null", async () => {
    mockList();
    let body: unknown;
    server.use(
      http.patch("/api/tasks/:id", async ({ request }) => {
        body = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Edit Sign handbook" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit task" });
    await user.clear(within(dialog).getByRole("textbox", { name: /Description/ }));
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(body).toBeDefined());
    expect(body).toEqual({ description: "" });
  });

  it("delete confirms then DELETEs", async () => {
    const calls = mockList();
    let deleted = "";
    server.use(
      http.delete("/api/tasks/:id", ({ params }) => {
        deleted = String(params.id);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Delete Meet buddy" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(deleted).toBe("");
    const before = calls.all;
    await user.click(within(dialog).getByRole("button", { name: "Yes, delete" }));
    await waitFor(() => expect(deleted).toBe("a2"));
    await waitFor(() => expect(calls.all).toBeGreaterThan(before));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  describe("reorder", () => {
    it("Move down swaps positions with the next task in the same group, in order", async () => {
      mockList();
      const seen: { id: string; body: unknown }[] = [];
      server.use(
        http.patch("/api/tasks/:id", async ({ params, request }) => {
          seen.push({ id: String(params.id), body: await request.json() });
          return new HttpResponse(null, { status: 204 });
        }),
      );
      const user = userEvent.setup();
      renderTab();
      await user.click(await screen.findByRole("button", { name: "Move down Set up laptop" }));
      await waitFor(() => expect(seen).toHaveLength(2));
      expect(seen).toEqual([
        { id: "p1", body: { position: 2 } },
        { id: "p2", body: { position: 1 } },
      ]);
    });

    it("Move up swaps with the previous task", async () => {
      mockList();
      const seen: { id: string; body: unknown }[] = [];
      server.use(
        http.patch("/api/tasks/:id", async ({ params, request }) => {
          seen.push({ id: String(params.id), body: await request.json() });
          return new HttpResponse(null, { status: 204 });
        }),
      );
      const user = userEvent.setup();
      renderTab();
      await user.click(await screen.findByRole("button", { name: "Move up Join on-call" }));
      await waitFor(() => expect(seen).toHaveLength(2));
      expect(seen).toEqual([
        { id: "p3", body: { position: 2 } },
        { id: "p2", body: { position: 3 } },
      ]);
    });

    it("the first task's Move up and the last task's Move down are disabled", async () => {
      mockList();
      renderTab();
      expect(await screen.findByRole("button", { name: "Move up Set up laptop" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Move up Ship first PR" })).toBeEnabled();
      expect(screen.getByRole("button", { name: "Move down Join on-call" })).toBeDisabled();
      // groups do not bleed into each other
      expect(screen.getByRole("button", { name: "Move up Sign handbook" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Move down Meet buddy" })).toBeDisabled();
    });

    it("disables every move control while a swap is in flight", async () => {
      mockList();
      let patches = 0;
      server.use(
        http.patch("/api/tasks/:id", async () => {
          patches += 1;
          await delay(150);
          return new HttpResponse(null, { status: 204 });
        }),
      );
      const user = userEvent.setup();
      renderTab();
      await user.click(await screen.findByRole("button", { name: "Move down Set up laptop" }));
      expect(screen.getByRole("button", { name: "Move down Ship first PR" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Move up Join on-call" })).toBeDisabled();
      await waitFor(() => expect(patches).toBe(2));
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Move up Join on-call" })).toBeEnabled(),
      );
    });

    it("a failed second PATCH restores the first task's original position", async () => {
      mockList();
      const seen: { id: string; body: unknown }[] = [];
      server.use(
        http.patch("/api/tasks/:id", async ({ params, request }) => {
          seen.push({ id: String(params.id), body: await request.json() });
          if (params.id === "p2")
            return HttpResponse.json({ detail: "not_found" }, { status: 404 });
          return new HttpResponse(null, { status: 204 });
        }),
      );
      const user = userEvent.setup();
      renderTab();
      await user.click(await screen.findByRole("button", { name: "Move down Set up laptop" }));
      expect(await screen.findByRole("alert")).toBeInTheDocument();
      await waitFor(() => expect(seen).toHaveLength(3));
      expect(seen).toEqual([
        { id: "p1", body: { position: 2 } },
        { id: "p2", body: { position: 1 } },
        { id: "p1", body: { position: 1 } },
      ]);
    });

    it("moving between tasks with equal positions renumbers the group", async () => {
      mockList(tasks().map((t) => (t.group_id === "t1" ? { ...t, position: 1 } : t)));
      const seen: { id: string; body: unknown }[] = [];
      server.use(
        http.patch("/api/tasks/:id", async ({ params, request }) => {
          seen.push({ id: String(params.id), body: await request.json() });
          return new HttpResponse(null, { status: 204 });
        }),
      );
      const user = userEvent.setup();
      renderTab();
      await user.click(await screen.findByRole("button", { name: "Move down Set up laptop" }));
      await waitFor(() => expect(seen).toHaveLength(2));
      // New order p2, p1, p3 -> positions 1, 2, 3; p2 already holds 1.
      expect(seen).toEqual([
        { id: "p1", body: { position: 2 } },
        { id: "p3", body: { position: 3 } },
      ]);
    });

    it("shows messageFor copy when a swap fails", async () => {
      mockList();
      server.use(
        http.patch("/api/tasks/:id", () =>
          HttpResponse.json({ detail: "not_found" }, { status: 404 }),
        ),
      );
      const user = userEvent.setup();
      renderTab();
      await user.click(await screen.findByRole("button", { name: "Move down Set up laptop" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "That item no longer exists. It may have been moved or deleted.",
      );
    });
  });
});
