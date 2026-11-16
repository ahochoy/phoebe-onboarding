import { describe, expect, it, vi } from "vitest";
import { emitDemoReset, onDemoReset } from "./demoReset";

describe("demoReset bus", () => {
  it("notifies every subscriber and stops after unsubscribe", () => {
    const a = vi.fn();
    const b = vi.fn();
    const offA = onDemoReset(a);
    const offB = onDemoReset(b);
    emitDemoReset();
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
    offA();
    emitDemoReset();
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(2);
    offB();
  });
});
