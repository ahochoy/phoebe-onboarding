import { useSyncExternalStore } from "react";

/** Tailwind's `md` breakpoint. */
export const MD_UP = "(min-width: 768px)";

/** Tailwind's `lg` breakpoint: the employee page's three-column layout. */
export const LG_UP = "(min-width: 1024px)";

/** Tracks whether a CSS media query currently matches. False where matchMedia is missing. */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window.matchMedia !== "function") return () => {};
      const mql = window.matchMedia(query);
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    },
    () => (typeof window.matchMedia === "function" ? window.matchMedia(query).matches : false),
    () => false,
  );
}
