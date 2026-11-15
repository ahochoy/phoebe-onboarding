import confetti from "canvas-confetti";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { celebrate } from "./celebrate";

vi.mock("canvas-confetti", () => ({ default: vi.fn() }));

function stubMotion(reduce: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: reduce && query === "(prefers-reduced-motion: reduce)",
  })) as unknown as typeof window.matchMedia;
}

describe("celebrate", () => {
  beforeEach(() => vi.mocked(confetti).mockClear());
  afterEach(() => {
    // jsdom has no matchMedia; remove the stub so other files are unaffected.
    Reflect.deleteProperty(window, "matchMedia");
  });

  it("fires confetti once when motion is allowed", () => {
    stubMotion(false);
    celebrate();
    expect(confetti).toHaveBeenCalledTimes(1);
  });

  it("does nothing under prefers-reduced-motion", () => {
    stubMotion(true);
    celebrate();
    expect(confetti).not.toHaveBeenCalled();
  });
});
