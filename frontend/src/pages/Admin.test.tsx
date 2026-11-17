import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { MD_UP } from "../lib/useMediaQuery";
import { useSession } from "../test/fixtures";
import { renderApp } from "../test/render";
import { server } from "../test/server";

const realMatchMedia = window.matchMedia;

function setWide(wide: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: query === MD_UP ? wide : false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

describe("Admin shell", () => {
  beforeEach(() => {
    useSession();
    server.use(http.get("/api/people", () => HttpResponse.json([])));
  });
  afterEach(() => {
    window.matchMedia = realMatchMedia;
  });

  it("vertical tabs Home, People & Progress, Documents, Tasks, Groups; URL follows selection", async () => {
    setWide(true);
    const user = userEvent.setup();
    const { router } = renderApp("/admin/people");
    const list = await screen.findByRole("tablist");
    expect(list).toHaveAttribute("aria-orientation", "vertical");
    const tabs = within(list).getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual([
      "Home",
      "People & Progress",
      "Documents",
      "Tasks",
      "Groups",
    ]);
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");

    await user.click(within(list).getByRole("tab", { name: "Tasks" }));
    expect(router.state.location.pathname).toBe("/admin/tasks");
    expect(within(list).getByRole("tab", { name: "Tasks" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tabpanel", { name: "Tasks" })).toBeInTheDocument();
  });

  it("the tab follows the URL when it changes elsewhere", async () => {
    setWide(true);
    const { router } = renderApp("/admin/people");
    await screen.findByRole("tablist");
    await act(() => router.navigate("/admin/groups"));
    expect(screen.getByRole("tab", { name: "Groups" })).toHaveAttribute("aria-selected", "true");
  });

  it("below md the tab list is horizontal and scrolls", async () => {
    setWide(false);
    renderApp("/admin/documents");
    const list = await screen.findByRole("tablist");
    expect(list).toHaveAttribute("aria-orientation", "horizontal");
    expect(list.className).toContain("overflow-x-auto");
    expect(screen.getByRole("tab", { name: "Documents" })).toHaveAttribute("aria-selected", "true");
  });

  it("an unknown tab redirects to Home", async () => {
    setWide(true);
    const { router } = renderApp("/admin/nope");
    await screen.findByRole("tablist");
    expect(router.state.location.pathname).toBe("/admin/home");
  });

  it("/admin redirects to Home", async () => {
    setWide(true);
    const { router } = renderApp("/admin");
    await screen.findByRole("tablist");
    expect(router.state.location.pathname).toBe("/admin/home");
  });
});
