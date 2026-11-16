import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { OPEN, unauthorized, useSession } from "./test/fixtures";
import { makeClient, renderApp } from "./test/render";
import { server } from "./test/server";

describe("routes under a preview base path", () => {
  it("navigates within the base while /api calls stay at the origin root", async () => {
    useSession();
    const apiPaths: string[] = [];
    server.events.on("request:start", ({ request }) => {
      apiPaths.push(new URL(request.url).pathname);
    });

    const user = userEvent.setup();
    const { router } = renderApp("/pr-12/employee", makeClient(), "/pr-12");
    expect(await screen.findByRole("heading", { name: "Chat" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/pr-12/employee");

    await user.click(screen.getByRole("radio", { name: "Admin" }));
    expect(await screen.findByRole("heading", { name: "People & Progress" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/pr-12/admin/people");

    expect(apiPaths).toContain("/api/me");
    expect(apiPaths.every((p) => p.startsWith("/api/"))).toBe(true);
  });

  it("falls back to the landing page inside the base", async () => {
    server.use(
      http.get("/api/me", unauthorized),
      http.get("/api/status", () => HttpResponse.json(OPEN)),
    );
    const { router } = renderApp("/pr-12/nowhere", makeClient(), "/pr-12");
    await screen.findByLabelText(/password/i);
    expect(router.state.location.pathname).toBe("/pr-12");
  });
});
