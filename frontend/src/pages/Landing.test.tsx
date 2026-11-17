import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { CLOSED, GROUPS, ME, OPEN, unauthorized } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server } from "../test/server";

function signedOut(status = OPEN) {
  server.use(
    http.get("/api/me", unauthorized),
    http.get("/api/status", () => HttpResponse.json(status)),
  );
}

describe("Landing", () => {
  it("shows password form, mascot and one-line description", async () => {
    signedOut();
    const { container } = renderApp("/");
    expect(await screen.findByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /enter|start|sign in/i })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Welcome to Larkspur Labs. I'm Phoebe, your onboarding guide.",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/ask a question and get answers/i)).toBeInTheDocument();
    expect(container.querySelector('img[aria-hidden="true"][alt=""]')).not.toBeNull();
  });

  it('wrong password shows "That password didn\'t work." and the field keeps focus', async () => {
    signedOut();
    server.use(
      http.post("/api/login", () =>
        HttpResponse.json({ detail: "invalid_password" }, { status: 401 }),
      ),
    );
    const user = userEvent.setup();
    renderApp("/");
    const field = await screen.findByLabelText(/password/i);
    await user.type(field, "nope");
    await user.click(screen.getByRole("button", { name: /enter|start|sign in/i }));
    expect(await screen.findByText("That password didn't work.")).toBeInTheDocument();
    expect(field).toHaveFocus();
    expect(field).toHaveAttribute("aria-invalid", "true");
  });

  it('login success navigates to /employee, then shows "Getting Phoebe ready…" while /api/me is pending', async () => {
    let loggedIn = false;
    // The post-login /api/me response is held until the test releases it, so the
    // pending state is observable without racing a timer.
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get("/api/status", () => HttpResponse.json(OPEN)),
      http.get("/api/groups", () => HttpResponse.json(GROUPS)),
      http.get("/api/me", async () => {
        if (!loggedIn) return unauthorized();
        await held;
        return HttpResponse.json(ME);
      }),
      http.post("/api/login", () => {
        loggedIn = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    const { router } = renderApp("/");
    await user.type(await screen.findByLabelText(/password/i), "secret{Enter}");
    try {
      // The state is held, not transient, so a generous timeout only absorbs slow renders.
      expect(
        await screen.findByText("Getting Phoebe ready…", {}, { timeout: 4000 }),
      ).toBeInTheDocument();
      await waitFor(() => expect(router.state.location.pathname).toBe("/employee"), {
        timeout: 4000,
      });
      expect(screen.queryByText("Alex Rivera")).not.toBeInTheDocument();
    } finally {
      release();
    }
    expect(await screen.findByText("Alex Rivera", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/employee");
  });

  it("closed state shows offline copy and no form", async () => {
    signedOut(CLOSED);
    renderApp("/");
    expect(
      await screen.findByText("The Phoebe demo is temporarily offline. Please check back later."),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
  });
});
