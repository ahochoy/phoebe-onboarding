import { describe, expect, it } from "vitest";
import { cpToUtf16 } from "./offsets";

describe("cpToUtf16", () => {
  it("is the identity for ASCII", () => {
    expect(cpToUtf16("hello", 0)).toBe(0);
    expect(cpToUtf16("hello", 3)).toBe(3);
    expect(cpToUtf16("hello", 5)).toBe(5);
  });

  it("counts an astral character as two UTF-16 units", () => {
    expect(cpToUtf16("🎉ab", 1)).toBe(2);
  });

  it("handles several astral characters", () => {
    expect(cpToUtf16("a🎉b🎉c", 4)).toBe(6);
  });

  it("clamps past-the-end and negative values", () => {
    expect(cpToUtf16("🎉ab", 99)).toBe(4);
    expect(cpToUtf16("🎉ab", -3)).toBe(0);
  });
});
