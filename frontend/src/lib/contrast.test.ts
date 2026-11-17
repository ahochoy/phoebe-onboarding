/// <reference types="node" />
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "../styles.css"), "utf8");

function token(name: string): string {
  const match = new RegExp(`--color-${name}:\\s*(#[0-9a-fA-F]{6})`).exec(css);
  if (!match) throw new Error(`missing token --color-${name}`);
  return match[1] as string;
}

function luminance(hex: string): number {
  const lin = (i: number) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(1) + 0.7152 * lin(3) + 0.0722 * lin(5);
}

function ratio(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

describe("palette contrast (WCAG AA, 4.5:1)", () => {
  it("accent on surface", () => {
    expect(ratio(token("accent"), token("surface"))).toBeGreaterThanOrEqual(4.5);
  });
  it("white text on accent", () => {
    expect(ratio(token("accent"), "#ffffff")).toBeGreaterThanOrEqual(4.5);
  });
  it("highlight on white", () => {
    expect(ratio(token("highlight"), "#ffffff")).toBeGreaterThanOrEqual(4.5);
  });
  it("ink on surface", () => {
    expect(ratio(token("ink"), token("surface"))).toBeGreaterThanOrEqual(4.5);
  });
  it("warn and danger on highlight-soft", () => {
    for (const t of ["warn", "danger", "ok"]) {
      expect(ratio(token(t), token("highlight-soft"))).toBeGreaterThanOrEqual(4.5);
    }
  });
});
