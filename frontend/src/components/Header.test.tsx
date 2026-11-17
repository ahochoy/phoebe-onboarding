import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { useSession } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server } from "../test/server";

describe("Header", () => {
  it("shows only the Larkspur Labs logo on the left: no tool name or persona details", async () => {
    useSession();
    renderApp("/employee");
    const header = within(await screen.findByRole("banner"));
    expect(header.getByRole("img", { name: "Larkspur Labs" })).toBeInTheDocument();
    await screen.findByRole("heading", { name: "Chat" });
    expect(header.queryByText("Phoebe")).not.toBeInTheDocument();
    expect(header.queryByText("Alex Rivera")).not.toBeInTheDocument();
    expect(header.queryByText(/Day 5/)).not.toBeInTheDocument();
    expect(header.queryByText(/Nov 10, 2026/)).not.toBeInTheDocument();
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
    await waitFor(() => expect(router.state.location.pathname).toBe("/admin/home"));
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
