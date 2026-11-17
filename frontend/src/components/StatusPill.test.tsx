import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { StatusOut } from "../api/types";
import { OPEN, PAUSED } from "../test/fixtures";

const CAPPED: StatusOut = { ...OPEN, reasons: ["global_chat_limit"] };
import { makeClient } from "../test/render";
import { server } from "../test/server";
import { StatusPill } from "./StatusPill";

const COPY = "Rate limit exceeded. Please wait for sessions to refresh.";
const TIP =
  "You can still browse Phoebe and explore the UX. Chat and document upload are paused until limits reset.";

function setup(status: StatusOut) {
  let hits = 0;
  server.use(
    http.get("/api/status", () => {
      hits += 1;
      return HttpResponse.json(status);
    }),
  );
  render(
    <QueryClientProvider client={makeClient()}>
      <StatusPill />
    </QueryClientProvider>,
  );
  return () => hits;
}

describe("StatusPill", () => {
  it("hidden when open and no reasons", async () => {
    const hits = setup(OPEN);
    await new Promise((r) => setTimeout(r, 100));
    expect(hits()).toBeGreaterThan(0);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("hidden when chat_paused: the spend banner says it instead", async () => {
    const hits = setup(PAUSED);
    await new Promise((r) => setTimeout(r, 100));
    expect(hits()).toBeGreaterThan(0);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows for a cap reason even when the state is open", async () => {
    setup({ ...OPEN, reasons: ["session_chat_limit"] });
    expect(await screen.findByRole("button", { name: COPY })).toBeInTheDocument();
  });

  it("tooltip opens on hover with exact copy", async () => {
    setup(CAPPED);
    const user = userEvent.setup();
    await user.hover(await screen.findByRole("button", { name: COPY }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent(TIP);
  });

  it("tooltip opens on keyboard focus with exact copy", async () => {
    setup(CAPPED);
    const user = userEvent.setup();
    await screen.findByRole("button", { name: COPY });
    await user.tab();
    expect(await screen.findByRole("tooltip")).toHaveTextContent(TIP);
  });

  it("tap opens the popover with exact copy", async () => {
    setup(CAPPED);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: COPY }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(TIP)).toBeInTheDocument();
  });
});
