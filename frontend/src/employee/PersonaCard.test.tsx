import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { ME, useSession } from "../test/fixtures";
import { makeClient } from "../test/render";
import { server } from "../test/server";
import { initials } from "./photos";
import { DayStrip, PersonaCard } from "./PersonaCard";

function useCard(me: Partial<typeof ME> = {}) {
  useSession();
  server.use(http.get("/api/me", () => HttpResponse.json({ ...ME, ...me })));
  return render(
    <QueryClientProvider client={makeClient()}>
      <DayStrip />
      <PersonaCard />
    </QueryClientProvider>,
  );
}

describe("initials", () => {
  it("takes the first and last initials, uppercase", () => {
    expect(initials("Melinda Grant")).toBe("MG");
    expect(initials("Cher")).toBe("C");
    expect(initials("  ")).toBe("?");
  });
});

describe("PersonaCard", () => {
  it("shows photos, names and roles for the manager and the buddy", async () => {
    const { container } = useCard();
    await screen.findByText("Melinda Grant");
    expect(container.querySelector('img[src*="melinda-grant"]')).toBeInTheDocument();
    expect(screen.getByText("Engineering Manager, Platform")).toBeInTheDocument();
    expect(container.querySelector('img[src*="jordan-moore"]')).toBeInTheDocument();
    expect(screen.getByText("Jordan Moore")).toBeInTheDocument();
    expect(screen.getByText("Senior Engineer")).toBeInTheDocument();
  });

  it("falls back to initials when a person has no photo", async () => {
    const { container } = useCard({ manager: "Elena Petrova", manager_role: null });
    expect(await screen.findByText("Elena Petrova")).toBeInTheDocument();
    expect(screen.getByText("EP")).toBeInTheDocument();
    expect(container.querySelector('img[src*="melinda-grant"]')).not.toBeInTheDocument();
    expect(screen.queryByText("null")).not.toBeInTheDocument();
  });

  it("shows Not assigned when there is no manager", async () => {
    useCard({ manager: null, manager_role: null });
    expect(await screen.findByText("Not assigned")).toBeInTheDocument();
  });
});

describe("DayStrip", () => {
  it("is sticky and shows the day and start date", async () => {
    useCard();
    const day = await screen.findByText(/^Day 5/);
    expect(day).toHaveTextContent("Day 5 · Started Nov 10, 2026");
    expect(day.closest(".sticky")).not.toBeNull();
  });
});
