import { describe, expect, it } from "vitest";
import { isWebUrl } from "./links";

describe("isWebUrl", () => {
  it("allows http(s) URLs", () => {
    expect(isWebUrl("https://example.com/a")).toBe(true);
    expect(isWebUrl("HTTP://example.com")).toBe(true);
  });

  it("allows same-origin absolute paths", () => {
    expect(isWebUrl("/seed-sources/benefits.html")).toBe(true);
  });

  it("rejects protocol-relative and script URLs", () => {
    expect(isWebUrl("//evil.example")).toBe(false);
    expect(isWebUrl("javascript:alert(1)")).toBe(false);
    expect(isWebUrl("data:text/html,hi")).toBe(false);
    expect(isWebUrl("/\\evil.example")).toBe(false);
    expect(isWebUrl("relative/path")).toBe(false);
  });
});
