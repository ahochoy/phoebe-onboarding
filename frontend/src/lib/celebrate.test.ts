import confetti from "canvas-confetti";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { celebrate } from "./celebrate";

const fire = vi.hoisted(() => vi.fn());
vi.mock("canvas-confetti", () => ({
  default: Object.assign(vi.fn(), { create: vi.fn(() => fire), reset: vi.fn() }),
}));

function stubMotion(reduce: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: reduce && query === "(prefers-reduced-motion: reduce)",
  })) as unknown as typeof window.matchMedia;
}

describe("celebrate", () => {
  beforeEach(() => fire.mockClear());
  afterEach(() => {
    // jsdom has no matchMedia; remove the stub so other files are unaffected.
    Reflect.deleteProperty(window, "matchMedia");
  });

  it("fires one burst per call when motion is allowed, from one main-thread instance (no blob: worker)", () => {
    stubMotion(false);
    celebrate();
    expect(fire).toHaveBeenCalledTimes(1);
    celebrate();
    expect(fire).toHaveBeenCalledTimes(2);
    expect(confetti).not.toHaveBeenCalled();
    expect(confetti.create).toHaveBeenCalledTimes(1);
    expect(confetti.create).toHaveBeenCalledWith(undefined, { useWorker: false, resize: true });
  });

  it("does nothing under prefers-reduced-motion", () => {
    stubMotion(true);
    celebrate();
    expect(fire).not.toHaveBeenCalled();
  });
});
