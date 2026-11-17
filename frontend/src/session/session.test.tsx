import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  it("the signed-in app nudges the database awake once on arrival", async () => {
    useSession();
    let wakes = 0;
    server.use(
      http.post("/api/wake", () => {
        wakes += 1;
        return HttpResponse.json({ database: "waking" }, { status: 202 });
      }),
    );
    renderApp("/employee");
    expect(await screen.findByRole("heading", { name: "Chat" })).toBeInTheDocument();
    await waitFor(() => expect(wakes).toBe(1));
  });

  it("the public landing page never wakes the database", async () => {
    let wakes = 0;
    server.use(
      http.get("/api/me", unauthorized),
      http.get("/api/status", () => HttpResponse.json(OPEN)),
      http.post("/api/wake", () => {
        wakes += 1;
        return HttpResponse.json({ database: "awake" });
      }),
    );
    renderApp("/");
    expect(await screen.findByLabelText(/password/i)).toBeInTheDocument();
    expect(wakes).toBe(0);
  });

  it("redirects /admin to /admin/home", async () => {
    useSession();
    const { router } = renderApp("/admin");
    await waitFor(() => expect(router.state.location.pathname).toBe("/admin/home"));
    expect(await screen.findByRole("heading", { name: "Home" })).toBeInTheDocument();
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

  const ENDED = "Your session ended. Enter the password to start again.";

  it("a first-time visitor deep-linking to /employee sees no session-ended message", async () => {
    server.use(
      http.get("/api/me", unauthorized),
      http.get("/api/status", () => HttpResponse.json(OPEN)),
    );
    const { router } = renderApp("/employee");
    expect(await screen.findByLabelText(/password/i)).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");
    expect(screen.queryByText(ENDED)).not.toBeInTheDocument();
  });

  it("after a login the marker is set and a later 401 shows the session-ended message", async () => {
    let loggedIn = false;
    server.use(
      http.get("/api/me", () => (loggedIn ? HttpResponse.json(ME) : unauthorized())),
      http.get("/api/status", () => HttpResponse.json(OPEN)),
      http.get("/api/groups", () => HttpResponse.json(GROUPS)),
      http.get("/api/tasks", () => (loggedIn ? HttpResponse.json([]) : unauthorized())),
      http.get("/api/documents", () => HttpResponse.json([])),
      http.get("/api/chat/history", () => HttpResponse.json([])),
      http.post("/api/login", () => {
        loggedIn = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderApp("/");
    await user.type(await screen.findByLabelText(/password/i), "secret{Enter}");
    expect(await screen.findByText("Alex Rivera", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(window.sessionStorage.getItem("phoebe.hadSession")).not.toBeNull();

    loggedIn = false;
    await expect(apiGet("/api/tasks")).rejects.toMatchObject({ code: "session_expired" });
    expect(await screen.findByText(ENDED)).toBeInTheDocument();
  });

  it("logout clears the marker", async () => {
    useSession();
    server.use(http.post("/api/logout", () => new HttpResponse(null, { status: 204 })));
    const user = userEvent.setup();
    renderApp("/employee");
    expect(await screen.findByRole("heading", { name: "Chat" })).toBeInTheDocument();
    expect(window.sessionStorage.getItem("phoebe.hadSession")).not.toBeNull();

    await user.click(screen.getByRole("button", { name: "Log out" }));
    await waitFor(() => expect(window.sessionStorage.getItem("phoebe.hadSession")).toBeNull());
  });
});
