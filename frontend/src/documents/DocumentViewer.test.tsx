import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DocumentDetailOut } from "../api/types";
import { makeDetail } from "../test/fixtures";
import { makeClient } from "../test/render";
import { server } from "../test/server";
import { ViewerProvider, useViewer } from "./ViewerProvider";

function setWide(wide: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: wide,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}

function Trigger({ passage }: { passage?: { start: number; end: number } }) {
  const viewer = useViewer();
  return (
    <button type="button" onClick={() => viewer.open("d1", passage)}>
      Open doc
    </button>
  );
}

function serve(detail: DocumentDetailOut) {
  server.use(http.get("/api/documents/d1", () => HttpResponse.json(detail)));
}

async function openViewer(passage?: { start: number; end: number }) {
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={makeClient()}>
      <ViewerProvider>
        <Trigger passage={passage} />
      </ViewerProvider>
    </QueryClientProvider>,
  );
  await user.click(screen.getByRole("button", { name: "Open doc" }));
  return user;
}

afterEach(() => {
  setWide(false);
  vi.restoreAllMocks();
});

describe("DocumentViewer", () => {
  it("renders sections with their heading paths as headings", async () => {
    const text = "Alpha body\nBeta body\nGamma body";
    serve(
      makeDetail("d1", {
        title: "Handbook",
        full_text: text,
        sections: [
          { heading_path: ["Handbook"], start: 0, end: 10 },
          { heading_path: ["Handbook", "Benefits"], start: 11, end: 20 },
          { heading_path: ["Handbook", "Benefits", "PTO"], start: 21, end: 31 },
        ],
      }),
    );
    await openViewer();

    expect(await screen.findByRole("heading", { level: 2, name: "Handbook" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Benefits" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "PTO" })).toBeInTheDocument();
    expect(screen.getByText("Gamma body")).toBeInTheDocument();
  });

  it("highlights exactly the cited passage when the text before it has an emoji", async () => {
    const text = "🎉 Intro\nPTO is 20 days.";
    // Code points: the emoji is one, so the body starts at 8 and is 15 long.
    serve(
      makeDetail("d1", {
        full_text: text,
        sections: [{ heading_path: ["Intro"], start: 8, end: 23 }],
      }),
    );
    await openViewer({ start: 8, end: 23 });

    const mark = await screen.findByText("PTO is 20 days.", { selector: "mark" });
    expect(mark.textContent).toBe("PTO is 20 days.");
  });

  it("highlights a passage that crosses sections in every section", async () => {
    const text = "One two\nthree four";
    serve(
      makeDetail("d1", {
        full_text: text,
        sections: [
          { heading_path: ["A"], start: 0, end: 7 },
          { heading_path: ["B"], start: 8, end: 18 },
        ],
      }),
    );
    await openViewer({ start: 4, end: 13 });

    await screen.findByRole("heading", { name: "B" });
    const marks = Array.from(document.querySelectorAll("mark")).map((m) => m.textContent);
    expect(marks).toEqual(["two", "three"]);
  });

  it("scrolls the mark into view", async () => {
    const spy = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => {});
    serve(
      makeDetail("d1", {
        full_text: "Hello cited text here",
        sections: [{ heading_path: ["H"], start: 0, end: 21 }],
      }),
    );
    await openViewer({ start: 6, end: 16 });

    await screen.findByText("cited text", { selector: "mark" });
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
  });

  it("does not scroll or mark without a passage", async () => {
    const spy = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => {});
    serve(
      makeDetail("d1", {
        full_text: "Plain body",
        sections: [{ heading_path: ["H"], start: 0, end: 10 }],
      }),
    );
    await openViewer();
    await screen.findByText("Plain body");
    expect(document.querySelector("mark")).toBeNull();
    expect(spy).not.toHaveBeenCalled();
  });

  it.each(["web", "google_doc"] as const)(
    "%s shows a View original link to public_url",
    async (doc_type) => {
      serve(
        makeDetail("d1", {
          doc_type,
          public_url: "https://example.com/original",
          full_text: "Body",
          sections: [{ heading_path: ["H"], start: 0, end: 4 }],
        }),
      );
      await openViewer();
      const link = await screen.findByRole("link", { name: /View original/ });
      expect(link).toHaveAttribute("href", "https://example.com/original");
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    },
  );

  it("does not show View original for a pdf", async () => {
    serve(
      makeDetail("d1", { doc_type: "pdf", public_url: "https://example.com/x", full_text: "B" }),
    );
    await openViewer();
    await screen.findByRole("dialog");
    await screen.findByText("B");
    expect(screen.queryByRole("link", { name: /View original/ })).toBeNull();
  });

  it("processing document shows its status instead of text", async () => {
    serve(makeDetail("d1", { status: "processing", full_text: null }));
    await openViewer();
    expect(await screen.findByText(/still being processed/i)).toBeInTheDocument();
  });

  it("failed document shows failure_reason verbatim", async () => {
    serve(
      makeDetail("d1", {
        status: "failed",
        failure_reason: "PDF has <b>no</b> text layer (scanned?)",
        full_text: null,
      }),
    );
    await openViewer();
    expect(await screen.findByText("PDF has <b>no</b> text layer (scanned?)")).toBeInTheDocument();
    expect(screen.getByText(/could not be processed/i)).toBeInTheDocument();
  });

  it('404 shows "This document is no longer available."', async () => {
    server.use(
      http.get("/api/documents/d1", () =>
        HttpResponse.json({ detail: "not_found" }, { status: 404 }),
      ),
    );
    await openViewer();
    expect(await screen.findByText("This document is no longer available.")).toBeInTheDocument();
  });

  it("renders document text as plain text", async () => {
    serve(
      makeDetail("d1", {
        full_text: "<img src=x onerror=alert(1)>",
        sections: [{ heading_path: ["H"], start: 0, end: 28 }],
      }),
    );
    await openViewer();
    expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });

  describe.each([
    ["desktop side panel", true, "right-0"],
    ["mobile bottom sheet", false, "bottom-0"],
  ])("%s", (_name, wide, cls) => {
    it("uses the right layout, closes on Escape and returns focus", async () => {
      setWide(wide);
      serve(makeDetail("d1", { title: "Handbook", full_text: "Body" }));
      const user = await openViewer();

      const dialog = await screen.findByRole("dialog", { name: "Handbook" });
      expect(dialog.className).toContain(cls);

      await user.keyboard("{Escape}");
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      await waitFor(() => expect(screen.getByRole("button", { name: "Open doc" })).toHaveFocus());
    });
  });
});
