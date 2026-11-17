import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { StatusOut } from "../api/types";
import { OPEN, PAUSED } from "../test/fixtures";
import { makeClient } from "../test/render";
import { server } from "../test/server";
import { SpendBanner } from "./SpendBanner";
import { StatusPill } from "./StatusPill";

const BANNER =
  "Chat and uploads are paused to keep this demo within its spending limit. Everything else works as usual.";
const PILL = "Rate limit exceeded. Please wait for sessions to refresh.";

function setup(status: StatusOut) {
  server.use(http.get("/api/status", () => HttpResponse.json(status)));
  render(
    <QueryClientProvider client={makeClient()}>
      <SpendBanner />
      <StatusPill />
    </QueryClientProvider>,
  );
}

const settle = () => new Promise((r) => setTimeout(r, 100));

describe("SpendBanner", () => {
  it("shows the spend copy while paused", async () => {
    setup(PAUSED);
    expect(await screen.findByText(BANNER)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(BANNER);
  });

  it("renders nothing when open", async () => {
    setup(OPEN);
    await settle();
    expect(screen.queryByText(BANNER)).not.toBeInTheDocument();
  });

  it("renders nothing for a rate-limit cap alone, which keeps the pill", async () => {
    setup({ ...OPEN, reasons: ["session_chat_limit"] });
    expect(await screen.findByRole("button", { name: PILL })).toBeInTheDocument();
    expect(screen.queryByText(BANNER)).not.toBeInTheDocument();
  });

  it("shows only the banner when paused and capped", async () => {
    setup({ ...PAUSED, reasons: ["chat_paused", "global_chat_limit"] });
    expect(await screen.findByText(BANNER)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: PILL })).not.toBeInTheDocument();
  });
});
