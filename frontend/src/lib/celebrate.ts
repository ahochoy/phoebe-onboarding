import confetti from "canvas-confetti";

/** One burst of confetti. Does nothing for people who prefer reduced motion. */
export function celebrate(): void {
  if (typeof window.matchMedia !== "function") return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  void confetti({
    particleCount: 90,
    spread: 70,
    origin: { y: 0.7 },
    disableForReducedMotion: true,
  });
}
