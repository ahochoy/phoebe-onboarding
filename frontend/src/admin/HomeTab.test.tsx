import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";
import type { GroupNode, PersonProgress } from "../api/types";
import { makeDoc, useSession } from "../test/fixtures";
import { makeClient } from "../test/render";
import { server } from "../test/server";
import { HomeTab } from "./HomeTab";

const PEOPLE = [
  { person_id: "p1", name: "Alex", done: 2, total: 4 },
  { person_id: "p2", name: "Sam", done: 4, total: 4 },
] as PersonProgress[];

const TREE = [
  {
    id: "c",
    kind: "company",
    name: "Co",
    owned: false,
    parent_id: null,
    children: [
      { id: "d", kind: "department", name: "Eng", owned: false, parent_id: "c", children: [] },
    ],
  },
] as GroupNode[];

function renderHome() {
  return render(
    <QueryClientProvider client={makeClient()}>
      <MemoryRouter>
        <HomeTab />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("HomeTab", () => {
  beforeEach(() => {
    useSession();
    server.use(
      http.get("/api/people", () => HttpResponse.json(PEOPLE)),
      http.get("/api/groups", () => HttpResponse.json(TREE)),
      http.get("/api/documents", () =>
        HttpResponse.json([
          makeDoc("a", "company"),
          makeDoc("b", "company", { status: "processing" }),
          makeDoc("c", "company", { status: "failed" }),
        ]),
      ),
    );
  });

  it("shows four summary cards, each a link with its number", async () => {
    renderHome();
    const people = await screen.findByRole("link", { name: /People onboarding/ });
    expect(people).toHaveAttribute("href", "/admin/people");
    expect(within(people).getByText("2")).toBeInTheDocument();

    const docs = screen.getByRole("link", { name: /Documents/ });
    expect(docs).toHaveAttribute("href", "/admin/documents");
    expect(await within(docs).findByText("3")).toBeInTheDocument();

    const groups = screen.getByRole("link", { name: /Groups/ });
    expect(groups).toHaveAttribute("href", "/admin/groups");
    expect(await within(groups).findByText("2")).toBeInTheDocument();

    const tasks = screen.getByRole("link", { name: /Task completion/ });
    expect(tasks).toHaveAttribute("href", "/admin/people");
    expect(await within(tasks).findByText("75%")).toBeInTheDocument();
  });

  it("shows an error for a failed query", async () => {
    server.use(
      http.get("/api/groups", () => HttpResponse.json({ detail: "boom" }, { status: 500 })),
    );
    renderHome();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
