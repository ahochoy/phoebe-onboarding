import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { makeDetail, makeDoc } from "../test/fixtures";
import { makeClient } from "../test/render";
import { server } from "../test/server";
import { DocumentsPanel } from "./DocumentsPanel";
import { ViewerProvider } from "./ViewerProvider";

function renderPanel() {
  return render(
    <QueryClientProvider client={makeClient()}>
      <ViewerProvider>
        <DocumentsPanel />
      </ViewerProvider>
    </QueryClientProvider>,
  );
}

describe("DocumentsPanel", () => {
  it("groups documents by tier and shows type, title, purpose, last updated", async () => {
    server.use(
      http.get("/api/documents", () =>
        HttpResponse.json([
          makeDoc("t1", "team", { title: "Runbook", doc_type: "markdown", purpose: "On-call" }),
          makeDoc("c1", "company", {
            title: "Handbook",
            doc_type: "pdf",
            purpose: "Company rules",
            last_updated: "2026-11-03",
          }),
        ]),
      ),
    );
    renderPanel();

    const company = await screen.findByRole("region", { name: "Company" });
    expect(within(company).getByText("Handbook")).toBeInTheDocument();
    expect(within(company).getByText("Company rules")).toBeInTheDocument();
    expect(within(company).getByText("PDF")).toBeInTheDocument();
    expect(within(company).getByText("Nov 3, 2026")).toBeInTheDocument();

    const team = screen.getByRole("region", { name: "Platform" });
    expect(within(team).getByText("Runbook")).toBeInTheDocument();
    expect(within(team).getByText("Markdown")).toBeInTheDocument();

    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(["Company", "Platform"]);
  });

  it("clicking a row opens the viewer", async () => {
    server.use(
      http.get("/api/documents", () => HttpResponse.json([makeDoc("c1", "company")])),
      http.get("/api/documents/c1", () =>
        HttpResponse.json(makeDetail("c1", { title: "Doc c1", full_text: "Body text." })),
      ),
    );
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: /Doc c1/ }));
    expect(await screen.findByRole("dialog", { name: "Doc c1" })).toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    server.use(http.get("/api/documents", () => HttpResponse.json([])));
    renderPanel();
    expect(await screen.findByText(/no documents/i)).toBeInTheDocument();
  });
});
