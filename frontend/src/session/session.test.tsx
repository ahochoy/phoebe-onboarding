import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { apiGet } from "../api/client";
import { GROUPS, ME, OPEN, unauthorized, useSession } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server } from "../test/server";

describe("session", () => {
  it("skips landing when /api/me succeeds", async () => {
    useSession();
    const { router } = renderApp("/");
    expect(await screen.findByRole("heading", { name: "Chat" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/employee");
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
  });

  it("redirects /admin to /admin/people", async () => {
    useSession();
    const { router } = renderApp("/admin");
    await waitFor(() => expect(router.state.location.pathname).toBe("/admin/people"));
    expect(await screen.findByRole("heading", { name: "People & Progress" })).toBeInTheDocument();
  });

  it("401 session_expired anywhere returns to landing with the session-ended message", async () => {
    let expired = false;
    server.use(
      http.get("/api/me", () => (expired ? unauthorized() : HttpResponse.json(ME))),
      http.get("/api/status", () => HttpResponse.json(OPEN)),
      http.get("/api/groups", () => HttpResponse.json(GROUPS)),
      http.get("/api/tasks", () => (expired ? unauthorized() : HttpResponse.json([]))),
      http.get("/api/documents", () => HttpResponse.json([])),
    );
    const { router } = renderApp("/employee");
    expect(await screen.findByRole("heading", { name: "Chat" })).toBeInTheDocument();

    expired = true;
    await expect(apiGet("/api/tasks")).rejects.toMatchObject({ code: "session_expired" });

    expect(
      await screen.findByText("Your session ended. Enter the password to start again."),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");
    expect(await screen.findByLabelText(/password/i)).toBeInTheDocument();
  });
});
