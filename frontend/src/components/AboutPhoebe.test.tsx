import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ABOUT_PHOEBE, AboutPhoebe } from "./AboutPhoebe";

describe("AboutPhoebe", () => {
  it("is a fixed button in the bottom-right corner", () => {
    render(<AboutPhoebe />);
    const button = screen.getByRole("button", { name: "What is Phoebe?" });
    expect(button.closest(".fixed")).toHaveClass("bottom-4", "right-4");
  });

  it("explains Phoebe on hover", async () => {
    const user = userEvent.setup();
    render(<AboutPhoebe />);
    await user.hover(screen.getByRole("button", { name: "What is Phoebe?" }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent(ABOUT_PHOEBE);
  });

  it("explains Phoebe on keyboard focus too", async () => {
    const user = userEvent.setup();
    render(<AboutPhoebe />);
    await user.tab();
    expect(await screen.findByRole("tooltip")).toHaveTextContent("AWS");
  });

  it("says what it is: a RAG onboarding assistant built on AWS", () => {
    expect(ABOUT_PHOEBE).toMatch(/onboarding assistant/);
    expect(ABOUT_PHOEBE).toMatch(/retrieval-augmented generation/);
    expect(ABOUT_PHOEBE).toMatch(/AWS/);
  });
});
