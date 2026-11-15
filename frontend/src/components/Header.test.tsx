import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { useSession } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server } from "../test/server";

describe("Header", () => {
  it("shows Alex Rivera, Platform, start date and Day 5", async () => {
    useSession();
    renderApp("/employee");
    const header = within(await screen.findByRole("banner"));
    expect(await header.findByText("Alex Rivera")).toBeInTheDocument();
    expect(header.getByText("Platform")).toBeInTheDocument();
    expect(header.getByText(/Nov 10, 2026/)).toBeInTheDocument();
    expect(header.getByText("Day 5")).toBeInTheDocument();
    expect(await screen.findByText("Acme Corp")).toBeInTheDocument();
  });

  it("hides the persona block in admin mode", async () => {
    useSession();
    renderApp("/admin/people");
    expect(await screen.findByRole("heading", { name: "People & Progress" })).toBeInTheDocument();
    expect(screen.queryByText("Alex Rivera")).not.toBeInTheDocument();
  });

  it("toggle moves with arrow keys and selecting changes the route", async () => {
    useSession();
    const user = userEvent.setup();
    const { router } = renderApp("/employee");
    const employee = await screen.findByRole("radio", { name: "Employee" });
    expect(employee).toBeChecked();
    employee.focus();
    await user.keyboard("{ArrowRight}");
    const admin = screen.getByRole("radio", { name: "Admin" });
    expect(admin).toHaveFocus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(router.state.location.pathname).toBe("/admin/people"));
    expect(screen.getByRole("radio", { name: "Admin" })).toBeChecked();
    await user.click(screen.getByRole("radio", { name: "Employee" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/employee"));
  });

  it("Log out posts /api/logout and returns to landing", async () => {
    useSession();
    let csrf: string | null = null;
    server.use(
      http.post("/api/logout", ({ request }) => {
        csrf = request.headers.get("x-phoebe-csrf");
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    const { router } = renderApp("/employee");
    await user.click(await screen.findByRole("button", { name: "Log out" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
    expect(csrf).toBe("1");
  });
});
