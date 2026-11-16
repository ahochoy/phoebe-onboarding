import confetti from "canvas-confetti";

// The default instance draws in a blob: Worker, which a `default-src 'self'` CSP
// blocks. One instance on the main thread, created on first use and reused.
let fire: confetti.CreateTypes | null = null;

/** One burst of confetti. Does nothing for people who prefer reduced motion. */
export function celebrate(): void {
  if (typeof window.matchMedia !== "function") return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  fire ??= confetti.create(undefined, { useWorker: false, resize: true });
  void fire({
    particleCount: 90,
    spread: 70,
    origin: { y: 0.7 },
    disableForReducedMotion: true,
  });
}
