import { Popover, Tooltip } from "radix-ui";
import { Info } from "lucide-react";
import { useStatus } from "../state/status";

const PILL_COPY = "Rate limit exceeded. Please wait for sessions to refresh.";
const TIP_COPY =
  "You can still browse Phoebe and explore the UX. Chat and document upload are paused until limits reset.";

const bubble =
  "z-50 max-w-xs rounded-md border border-warn/40 bg-white px-3 py-2 text-sm text-ink shadow-md";

/**
 * Shown only while a rate-limit cap applies; a spend pause shows SpendBanner
 * instead (never both). The pill is one button: hover and keyboard
 * focus open the Tooltip, a tap (touch has no hover) opens the Popover.
 */
export function StatusPill() {
  const { paused, capped } = useStatus();
  if (!capped || paused) return null;
  return (
    <Tooltip.Provider delayDuration={150}>
      <Popover.Root>
        <Tooltip.Root>
          <Tooltip.Trigger asChild>
            <Popover.Trigger asChild>
              <button
                type="button"
                className="inline-flex min-h-6 cursor-pointer items-center gap-1.5 rounded-full border border-warn/50 bg-amber-50 px-3 py-1 text-sm font-medium text-warn"
              >
                <Info aria-hidden="true" className="size-4 shrink-0" />
                {PILL_COPY}
              </button>
            </Popover.Trigger>
          </Tooltip.Trigger>
          <Tooltip.Portal>
            <Tooltip.Content className={bubble} sideOffset={6}>
              {TIP_COPY}
            </Tooltip.Content>
          </Tooltip.Portal>
        </Tooltip.Root>
        <Popover.Portal>
          <Popover.Content className={bubble} sideOffset={6} aria-label="About the rate limit">
            {TIP_COPY}
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </Tooltip.Provider>
  );
}
