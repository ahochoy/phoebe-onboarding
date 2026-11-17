import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PetalLoader } from "./PetalLoader";
import { PhoebeArt, PhoebeAvatar, type Pose } from "./PhoebeArt";

const POSES: Pose[] = [
  "waving",
  "thinking",
  "pointing",
  "celebrating",
  "onboarding-checklist",
  "oops-error",
];

describe("PhoebeArt", () => {
  it.each(POSES)("renders the %s pose as a sized, decorative image", (pose) => {
    const { container } = render(<PhoebeArt pose={pose} size={96} />);
    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    expect(img?.getAttribute("src")).toContain(`phoebe-${pose}-256`);
    expect(img?.getAttribute("srcset")).toContain("512.webp 2x");
    expect(img).toHaveAttribute("alt", "");
    expect(img).toHaveAttribute("aria-hidden", "true");
    expect(img).toHaveAttribute("width", "96");
    expect(img).toHaveAttribute("height", "96");
  });

  it("renders the avatar crop", () => {
    const { container } = render(<PhoebeAvatar size={28} />);
    const img = container.querySelector("img");
    expect(img?.getAttribute("src")).toContain("phoebe-avatar-32");
    expect(img?.getAttribute("srcset")).toContain("64.webp 2x");
    expect(img).toHaveAttribute("aria-hidden", "true");
  });
});

describe("PetalLoader", () => {
  it("announces its label as a status", () => {
    render(<PetalLoader size={24} label="Getting Phoebe ready…" />);
    expect(screen.getByRole("status")).toHaveTextContent("Getting Phoebe ready…");
  });
});
