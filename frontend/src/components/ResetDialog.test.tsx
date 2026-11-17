import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { onDemoReset } from "../state/demoReset";
import { useSession } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server } from "../test/server";

function watchReset() {
  const seen = { posts: 0, csrf: null as string | null };
  server.use(
    http.post("/api/reset", ({ request }) => {
      seen.posts += 1;
      seen.csrf = request.headers.get("x-phoebe-csrf");
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return seen;
}

describe("Reset my demo", () => {
  it("asks for confirmation, POSTs /api/reset, then refetches every query", async () => {
    const calls = useSession();
    const seen = watchReset();
    const heard = vi.fn();
    const off = onDemoReset(heard);
    const user = userEvent.setup();
    renderApp("/employee");
    await user.click(await screen.findByRole("button", { name: "Reset my demo" }));
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(seen.posts).toBe(0);
    const before = { ...calls };

    await user.click(screen.getByRole("button", { name: "Yes, reset" }));

    await waitFor(() => expect(heard).toHaveBeenCalledTimes(1));
    expect(seen.posts).toBe(1);
    expect(seen.csrf).toBe("1");
    expect(calls.me).toBeGreaterThan(before.me);
    expect(calls.status).toBeGreaterThan(before.status);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    off();
  });

  it("Cancel sends nothing", async () => {
    useSession();
    const seen = watchReset();
    const heard = vi.fn();
    const off = onDemoReset(heard);
    const user = userEvent.setup();
    renderApp("/employee");
    await user.click(await screen.findByRole("button", { name: "Reset my demo" }));
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(seen.posts).toBe(0);
    expect(heard).not.toHaveBeenCalled();
    off();
  });
});
