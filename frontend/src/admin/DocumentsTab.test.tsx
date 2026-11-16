import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import type { DocumentOut, GroupNode } from "../api/types";
import { useDocuments } from "../documents/useDocuments";
import { messageFor, PAUSED_COPY } from "../lib/messages";
import { makeDoc, OPEN, useSession } from "../test/fixtures";
import { makeClient } from "../test/render";
import { server } from "../test/server";
import { DocumentsTab } from "./DocumentsTab";

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
      {
        id: "d2",
        kind: "department",
        name: "Sales",
        owned: false,
        parent_id: "c1",
        children: [],
      },
    ],
  },
];

const DOCS: DocumentOut[] = [
  makeDoc("a", "company", {
    title: "Handbook",
    purpose: "Company rules",
    doc_type: "pdf",
    group_id: "c1",
    group_name: "Acme Corp",
    status: "indexed",
  }),
  makeDoc("b", "team", {
    title: "Runbook",
    purpose: "On-call steps",
    doc_type: "markdown",
    group_id: "t1",
    group_name: "Platform",
    last_updated: null,
    status: "processing",
  }),
  makeDoc("c", "department", {
    title: "Pricing",
    purpose: "Price sheet",
    doc_type: "csv",
    group_id: "d2",
    group_name: "Sales",
    status: "failed",
    failure_reason: "Could not read the file",
  }),
];

const TOO_BIG = "Files must be 5 MB or smaller.";

function EmployeeProbe() {
  useDocuments();
  return null;
}

function renderTab(client = makeClient()) {
  render(
    <QueryClientProvider client={client}>
      <EmployeeProbe />
      <DocumentsTab />
    </QueryClientProvider>,
  );
  return client;
}

function mockList(docs: DocumentOut[] = DOCS) {
  const calls = { all: 0, mine: 0 };
  server.use(
    http.get("/api/documents", ({ request }) => {
      const scope = new URL(request.url).searchParams.get("scope");
      if (scope === "all") calls.all += 1;
      else calls.mine += 1;
      return HttpResponse.json(docs);
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

describe("DocumentsTab", () => {
  beforeEach(() => {
    useSession();
    server.use(http.get("/api/groups", () => HttpResponse.json(TREE)));
  });

  it("list shows title, type, group, purpose, last updated, status", async () => {
    mockList();
    renderTab();
    const table = await screen.findByRole("table", { name: "Documents" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["Title", "Type", "Group", "Purpose", "Last updated", "Status", "Actions"]);
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(4);
    const handbook = within(rows[1]!);
    expect(handbook.getByText("Handbook")).toBeInTheDocument();
    expect(handbook.getByText("PDF")).toBeInTheDocument();
    expect(handbook.getByText("Acme Corp")).toBeInTheDocument();
    expect(handbook.getByText("Company rules")).toBeInTheDocument();
    expect(handbook.getByText("Nov 3, 2026")).toBeInTheDocument();
    expect(handbook.getByText("Indexed ✓")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("Processing…")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("Markdown")).toBeInTheDocument();
    expect(within(rows[3]!).getByText("Failed: Could not read the file")).toBeInTheDocument();
  });

  describe("polling", () => {
    beforeEach(() => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
    });
    afterEach(() => {
      vi.useRealTimers();
    });

    it("while any doc is processing, the list refetches every 3 s and stops when none are", async () => {
      let docs = [...DOCS];
      const calls = mockList();
      server.use(
        http.get("/api/documents", ({ request }) => {
          if (new URL(request.url).searchParams.get("scope") === "all") calls.all += 1;
          return HttpResponse.json(docs);
        }),
      );
      renderTab();
      expect(await screen.findByText("Processing…")).toBeInTheDocument();
      expect(calls.all).toBe(1);

      await vi.advanceTimersByTimeAsync(3100);
      await waitFor(() => expect(calls.all).toBe(2));

      docs = docs.map((d) => (d.id === "b" ? { ...d, status: "indexed" as const } : d));
      await vi.advanceTimersByTimeAsync(3100);
      await waitFor(() => expect(calls.all).toBe(3));
      await waitFor(() => expect(screen.queryByText("Processing…")).not.toBeInTheDocument());

      await vi.advanceTimersByTimeAsync(12_000);
      expect(calls.all).toBe(3);
    });

    it("a failed poll keeps the table and shows a small inline note until the next poll succeeds", async () => {
      let fail = false;
      server.use(
        http.get("/api/documents", () =>
          fail
            ? HttpResponse.json({ detail: "internal_error" }, { status: 500 })
            : HttpResponse.json(DOCS),
        ),
      );
      renderTab();
      expect(await screen.findByText("Processing…")).toBeInTheDocument();

      fail = true;
      await vi.advanceTimersByTimeAsync(3100);
      const note = await screen.findByText(/This may be out of date\./);
      expect(note).toHaveAttribute("role", "status");
      expect(note).toHaveTextContent(messageFor(new ApiError(500, "internal_error")));
      expect(screen.getByRole("table", { name: "Documents" })).toBeInTheDocument();
      expect(screen.getByText("Handbook")).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();

      fail = false;
      await vi.advanceTimersByTimeAsync(3100);
      await waitFor(() =>
        expect(screen.queryByText(/This may be out of date\./)).not.toBeInTheDocument(),
      );
      expect(screen.getByRole("table", { name: "Documents" })).toBeInTheDocument();
    });
  });

  describe("upload", () => {
    it("upload sends multipart file,title,group_id,purpose,last_updated to /api/documents/upload", async () => {
      mockList();
      let form: FormData | undefined;
      server.use(
        http.post("/api/documents/upload", async ({ request }) => {
          form = await request.formData();
          return HttpResponse.json({ id: "n" }, { status: 202 });
        }),
      );
      const user = userEvent.setup();
      renderTab();
      await user.click(await screen.findByRole("button", { name: "Upload document" }));
      const dialog = await screen.findByRole("dialog", { name: "Upload a document" });

      const input = within(dialog).getByLabelText("File");
      expect(input).toHaveAttribute("accept", ".pdf,.md,.markdown,.csv");
      await user.upload(input, new File(["# Hi"], "guide.md", { type: "text/markdown" }));
      await user.type(within(dialog).getByRole("textbox", { name: /Title/ }), "Team guide");
      await pickGroup(user, dialog, "Platform");
      await user.type(within(dialog).getByRole("textbox", { name: /Purpose/ }), "How we work");
      await user.type(within(dialog).getByLabelText(/Last updated/), "2026-11-01");
      await user.click(within(dialog).getByRole("button", { name: "Upload" }));

      await waitFor(() => expect(form).toBeDefined());
      // jsdom's File crosses into Node's fetch as a bare Blob, so check the content, not the name.
      expect(await (form!.get("file") as Blob).text()).toBe("# Hi");
      expect(form!.get("title")).toBe("Team guide");
      expect(form!.get("group_id")).toBe("t1");
      expect(form!.get("purpose")).toBe("How we work");
      expect(form!.get("last_updated")).toBe("2026-11-01");
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    });

    it("sends empty purpose and last_updated when left blank", async () => {
      mockList();
      let form: FormData | undefined;
      server.use(
        http.post("/api/documents/upload", async ({ request }) => {
          form = await request.formData();
          return HttpResponse.json({ id: "n" }, { status: 202 });
        }),
      );
      const user = userEvent.setup();
      renderTab();
      await user.click(await screen.findByRole("button", { name: "Upload document" }));
      const dialog = await screen.findByRole("dialog", { name: "Upload a document" });
      await user.upload(
        within(dialog).getByLabelText("File"),
        new File(["a,b"], "t.csv", { type: "text/csv" }),
      );
      await user.type(within(dialog).getByRole("textbox", { name: /Title/ }), "T");
      await pickGroup(user, dialog, "Acme Corp");
      await user.click(within(dialog).getByRole("button", { name: "Upload" }));
      await waitFor(() => expect(form).toBeDefined());
      expect(form!.get("purpose")).toBe("");
      expect(form!.get("last_updated")).toBe("");
    });

    it("rejects files over 5 MB client-side and sends no request", async () => {
      mockList();
      let posted = 0;
      server.use(
        http.post("/api/documents/upload", () => {
          posted += 1;
          return HttpResponse.json({}, { status: 202 });
        }),
      );
      const user = userEvent.setup();
      renderTab();
      await user.click(await screen.findByRole("button", { name: "Upload document" }));
      const dialog = await screen.findByRole("dialog", { name: "Upload a document" });
      const big = new File(["x"], "big.pdf", { type: "application/pdf" });
      Object.defineProperty(big, "size", { value: 5 * 1024 * 1024 + 1 });
      const input = within(dialog).getByLabelText("File");
      await user.upload(input, big);
      expect(await within(dialog).findByText(TOO_BIG)).toBeInTheDocument();
      expect(input).toHaveAccessibleDescription(expect.stringContaining(TOO_BIG));
      await user.type(within(dialog).getByRole("textbox", { name: /Title/ }), "Big");
      await pickGroup(user, dialog, "Acme Corp");
      await user.click(within(dialog).getByRole("button", { name: "Upload" }));
      expect(within(dialog).getByText(TOO_BIG)).toBeInTheDocument();
      expect(posted).toBe(0);
    });

    it.each([
      [
        "415 shows the server's reason verbatim",
        415,
        { detail: "unsupported_type", reason: "Only PDF, Markdown and CSV files are accepted." },
        "Only PDF, Markdown and CSV files are accepted.",
      ],
      [
        "409 sandbox_full shows the mapped copy",
        409,
        { detail: "sandbox_full" },
        "The demo has reached its storage limit, so nothing new can be added. Delete something first.",
      ],
    ])("%s", async (_name, status, body, copy) => {
      mockList();
      server.use(http.post("/api/documents/upload", () => HttpResponse.json(body, { status })));
      const user = userEvent.setup();
      renderTab();
      await user.click(await screen.findByRole("button", { name: "Upload document" }));
      const dialog = await screen.findByRole("dialog", { name: "Upload a document" });
      await user.upload(
        within(dialog).getByLabelText("File"),
        new File(["x"], "a.pdf", { type: "application/pdf" }),
      );
      await user.type(within(dialog).getByRole("textbox", { name: /Title/ }), "A");
      await pickGroup(user, dialog, "Acme Corp");
      await user.click(within(dialog).getByRole("button", { name: "Upload" }));
      expect(await within(dialog).findByRole("alert")).toHaveTextContent(copy);
    });

    it("429 too_many_attempts from upload refetches status", async () => {
      mockList();
      let statusCalls = 0;
      server.use(
        http.get("/api/status", () => {
          statusCalls += 1;
          return HttpResponse.json(OPEN);
        }),
        http.post("/api/documents/upload", () =>
          HttpResponse.json({ detail: "too_many_attempts" }, { status: 429 }),
        ),
      );
      const user = userEvent.setup();
      renderTab();
      await user.click(await screen.findByRole("button", { name: "Upload document" }));
      const dialog = await screen.findByRole("dialog", { name: "Upload a document" });
      await waitFor(() => expect(statusCalls).toBe(1));
      await user.upload(
        within(dialog).getByLabelText("File"),
        new File(["x"], "a.pdf", { type: "application/pdf" }),
      );
      await user.type(within(dialog).getByRole("textbox", { name: /Title/ }), "A");
      await pickGroup(user, dialog, "Acme Corp");
      await user.click(within(dialog).getByRole("button", { name: "Upload" }));
      expect(await within(dialog).findByRole("alert")).toHaveTextContent(
        "Rate limit exceeded. Please wait for sessions to refresh.",
      );
      await waitFor(() => expect(statusCalls).toBe(2));
    });
  });

  describe("link", () => {
    async function openLink(user: ReturnType<typeof userEvent.setup>) {
      await user.click(await screen.findByRole("button", { name: "Add link" }));
      return screen.findByRole("dialog", { name: "Add a link" });
    }

    it("link form posts /api/documents/link", async () => {
      mockList();
      let body: unknown;
      server.use(
        http.post("/api/documents/link", async ({ request }) => {
          body = await request.json();
          return HttpResponse.json({ id: "n" }, { status: 202 });
        }),
      );
      const user = userEvent.setup();
      renderTab();
      const dialog = await openLink(user);
      await user.type(
        within(dialog).getByRole("textbox", { name: /Link address/ }),
        "https://example.com/a",
      );
      await user.type(within(dialog).getByRole("textbox", { name: /Title/ }), "Example");
      await pickGroup(user, dialog, "Engineering");
      await user.click(within(dialog).getByRole("button", { name: "Add link" }));
      await waitFor(() =>
        expect(body).toEqual({
          url: "https://example.com/a",
          title: "Example",
          purpose: "",
          group_id: "d1",
        }),
      );
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    });

    it("422 invalid_link shows the mapped copy", async () => {
      mockList();
      server.use(
        http.post("/api/documents/link", () =>
          HttpResponse.json({ detail: "invalid_link" }, { status: 422 }),
        ),
      );
      const user = userEvent.setup();
      renderTab();
      const dialog = await openLink(user);
      await user.type(within(dialog).getByRole("textbox", { name: /Link address/ }), "nope");
      await user.type(within(dialog).getByRole("textbox", { name: /Title/ }), "X");
      await pickGroup(user, dialog, "Acme Corp");
      await user.click(within(dialog).getByRole("button", { name: "Add link" }));
      expect(await within(dialog).findByRole("alert")).toHaveTextContent(
        "That link is not valid. Check the address and try again.",
      );
    });
  });

  it("upload disabled with tooltip copy when uploadAvailable is false", async () => {
    server.use(
      http.get("/api/status", () =>
        HttpResponse.json({ ...OPEN, upload_available: false, reasons: ["global_upload_limit"] }),
      ),
    );
    mockList();
    renderTab();
    const upload = await screen.findByRole("button", { name: "Upload document" });
    const link = screen.getByRole("button", { name: "Add link" });
    await waitFor(() => expect(upload).toBeDisabled());
    expect(link).toBeDisabled();
    expect(screen.getByText(PAUSED_COPY)).toBeVisible();
    expect(upload).toHaveAccessibleDescription(PAUSED_COPY);
    expect(link).toHaveAccessibleDescription(PAUSED_COPY);
  });

  describe("edit", () => {
    async function openEdit(user: ReturnType<typeof userEvent.setup>) {
      await user.click(await screen.findByRole("button", { name: "Edit Handbook" }));
      return screen.findByRole("dialog", { name: "Edit document" });
    }

    it("edit dialog PATCHes only changed fields", async () => {
      mockList();
      let body: unknown;
      server.use(
        http.patch("/api/documents/:id", async ({ request, params }) => {
          body = { id: params["id"], ...((await request.json()) as object) };
          return new HttpResponse(null, { status: 204 });
        }),
      );
      const user = userEvent.setup();
      renderTab();
      const dialog = await openEdit(user);
      const title = within(dialog).getByRole("textbox", { name: /Title/ });
      expect(title).toHaveValue("Handbook");
      await user.clear(title);
      await user.type(title, "Handbook 2");
      await user.click(within(dialog).getByRole("button", { name: "Save" }));
      await waitFor(() => expect(body).toEqual({ id: "a", title: "Handbook 2" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    });

    it("sends group_id when the group changes", async () => {
      mockList();
      let body: unknown;
      server.use(
        http.patch("/api/documents/:id", async ({ request }) => {
          body = await request.json();
          return new HttpResponse(null, { status: 204 });
        }),
      );
      const user = userEvent.setup();
      renderTab();
      const dialog = await openEdit(user);
      await pickGroup(user, dialog, "Sales");
      await user.click(within(dialog).getByRole("button", { name: "Save" }));
      await waitFor(() => expect(body).toEqual({ group_id: "d2" }));
    });

    it('clearing last updated sends {"last_updated": null}', async () => {
      mockList();
      let raw = "";
      server.use(
        http.patch("/api/documents/:id", async ({ request }) => {
          raw = await request.text();
          return new HttpResponse(null, { status: 204 });
        }),
      );
      const user = userEvent.setup();
      renderTab();
      const dialog = await openEdit(user);
      const date = within(dialog).getByLabelText(/Last updated/);
      expect(date).toHaveValue("2026-11-03");
      await user.clear(date);
      await user.click(within(dialog).getByRole("button", { name: "Save" }));
      await waitFor(() => expect(JSON.parse(raw)).toEqual({ last_updated: null }));
    });

    it("never sends a null title", async () => {
      mockList();
      let patched = 0;
      server.use(
        http.patch("/api/documents/:id", () => {
          patched += 1;
          return new HttpResponse(null, { status: 204 });
        }),
      );
      const user = userEvent.setup();
      renderTab();
      const dialog = await openEdit(user);
      await user.clear(within(dialog).getByRole("textbox", { name: /Title/ }));
      await user.click(within(dialog).getByRole("button", { name: "Save" }));
      expect(await within(dialog).findByText("Enter a title.")).toBeInTheDocument();
      expect(patched).toBe(0);
    });
  });

  it("delete asks for confirmation then DELETEs and invalidates ['documents'] and the employee documents query", async () => {
    const calls = mockList();
    let deleted: string | undefined;
    server.use(
      http.delete("/api/documents/:id", ({ params }) => {
        deleted = String(params["id"]);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Delete Handbook" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete this document?" });
    expect(deleted).toBeUndefined();
    await waitFor(() => expect(calls.mine).toBe(1));
    const allBefore = calls.all;
    await user.click(within(dialog).getByRole("button", { name: "Yes, delete" }));
    await waitFor(() => expect(deleted).toBe("a"));
    await waitFor(() => expect(calls.mine).toBe(2));
    await waitFor(() => expect(calls.all).toBe(allBefore + 1));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("cancelling the delete confirmation sends nothing", async () => {
    mockList();
    let deleted = 0;
    server.use(
      http.delete("/api/documents/:id", () => {
        deleted += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Delete Handbook" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(deleted).toBe(0);
  });
});
