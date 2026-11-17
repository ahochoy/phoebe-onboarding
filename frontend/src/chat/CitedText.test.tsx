import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CitedText } from "./CitedText";
import type { ChatMessage } from "./reducer";

type Cite = ChatMessage["citations"][number];

function cite(n: number): Cite {
  return {
    n,
    chunk_id: `k${n}`,
    document_id: `d${n}`,
    document_title: `Doc ${n}`,
    heading_path: "Section",
    start: 0,
    end: 5,
  };
}

function show(text: string, citations: Cite[] = [cite(1), cite(2)], onOpen = vi.fn()) {
  return render(<CitedText text={text} citations={citations} settled onOpen={onOpen} />);
}

describe("CitedText Markdown", () => {
  it("renders bold text and bulleted lists", () => {
    const { container } = show(
      "Holidays in November:\n\n- **Thanksgiving Day** (November 26) [1]\n- Day after Thanksgiving [2]",
    );
    expect(container.querySelector("strong")).toHaveTextContent("Thanksgiving Day");
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[1]!).getByRole("button", { name: "Source 2: Doc 2" })).toBeInTheDocument();
  });

  it("renders numbered lists", () => {
    show("1. First step [1]\n2. Second step [2]");
    expect(screen.getByRole("list").tagName).toBe("OL");
  });

  it("turns citation markers inside bold text into source buttons", async () => {
    const onOpen = vi.fn();
    const { container } = show("**Thanksgiving [1]** is a holiday.", [cite(1)], onOpen);
    const button = within(container.querySelector("strong")!).getByRole("button", {
      name: "Source 1: Doc 1",
    });
    await userEvent.click(button);
    expect(onOpen).toHaveBeenCalledWith(cite(1));
  });

  it("renders http links that open in a new tab", () => {
    show("See the [support calendar](https://example.com/cal) [1]", [cite(1)]);
    const link = screen.getByRole("link", { name: "support calendar" });
    expect(link).toHaveAttribute("href", "https://example.com/cal");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer nofollow");
  });

  it("drops javascript: links but keeps their text", () => {
    show("Click [here](javascript:alert(1)) [1]", [cite(1)]);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText(/here/)).toBeInTheDocument();
  });

  it("never renders raw HTML or images", () => {
    const { container } = show(
      'Hi <img src="x" onerror="alert(1)"> <b>bold</b> ![logo](https://example.com/x.png) [1]',
      [cite(1)],
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });

  it("renders Markdown headings as h3", () => {
    show("## November\n\nThanksgiving [1]", [cite(1)]);
    expect(screen.getByRole("heading", { level: 3, name: "November" })).toBeInTheDocument();
  });
});
