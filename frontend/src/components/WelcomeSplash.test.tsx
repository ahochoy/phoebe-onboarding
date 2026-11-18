import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { OPEN, unauthorized, useSession } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server } from "../test/server";

const WELCOME = "Welcome to the Platform team, Alex!";

describe("WelcomeSplash", () => {
  it("appears once after login, not after dismissing and reloading", async () => {
    useSession();
    // Before login the session is absent; afterwards the handler falls
    // through to useSession()'s /api/me.
    let loggedIn = false;
    server.use(
      http.get("/api/me", () => (loggedIn ? undefined : unauthorized())),
      http.post("/api/login", () => {
        loggedIn = true;
        return new HttpResponse(null, { status: 204 });
      }),
      http.get("/api/status", () => HttpResponse.json(OPEN)),
    );
    const user = userEvent.setup();
    const first = renderApp("/");
    await user.type(await screen.findByLabelText(/password/i), "secret{Enter}");
    const dialog = await screen.findByRole("dialog", { name: WELCOME });
    expect(dialog).toBeInTheDocument();
    // The mascot is static: no bounce.
    expect(dialog.querySelector("img")?.className).not.toMatch(/animate-/);
    await user.click(screen.getByRole("button", { name: /got it|let's go|continue/i }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(window.sessionStorage.getItem("phoebe.welcome")).toBe("done");
    first.unmount();

    renderApp("/employee");
    expect(await screen.findByRole("heading", { name: "Chat" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("does not appear for a session restored from /api/me", async () => {
    useSession();
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Chat" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
