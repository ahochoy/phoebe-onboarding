import { Info } from "lucide-react";
import { useStatus } from "../state/status";

const COPY =
  "Chat and uploads are paused to keep this demo within its spending limit. Everything else works as usual.";

/**
 * A strip across the top of the page while the demo is paused to stay within its
 * spend budget. No dismiss button: it goes away when the pause does.
 */
export function SpendBanner() {
  const { paused } = useStatus();
  if (!paused) return null;
  return (
    <div
      role="status"
      className="flex w-full items-start justify-center gap-2 border-b border-warn/50 bg-amber-50 px-4 py-2 text-sm font-medium text-warn"
    >
      <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <p>{COPY}</p>
    </div>
  );
}
