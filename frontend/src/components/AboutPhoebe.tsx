import { HelpCircle } from "lucide-react";
import { Popover, Tooltip } from "radix-ui";

export const ABOUT_PHOEBE =
  "Phoebe is Larkspur Labs' AI onboarding assistant. Ask a question and it searches " +
  "your team's onboarding documents with retrieval-augmented generation (RAG), then " +
  "answers with citations you can open. It runs on AWS: Amazon Bedrock " +
  "for the model, embeddings and guardrails, Aurora Serverless for search, and Lambda " +
  "behind CloudFront.";

const bubble =
  "z-50 max-w-xs rounded-md border border-ink/15 bg-white px-3 py-2 text-sm text-ink shadow-md";

/**
 * A small "?" in the bottom-right corner. Same pattern as the status pill: hover and
 * keyboard focus open the Tooltip, a tap (touch has no hover) opens the Popover.
 */
export function AboutPhoebe() {
  return (
    <div className="fixed right-4 bottom-4 z-40">
      <Tooltip.Provider delayDuration={150}>
        <Popover.Root>
          <Tooltip.Root>
            <Tooltip.Trigger asChild>
              <Popover.Trigger asChild>
                <button
                  type="button"
                  aria-label="What is Phoebe?"
                  className="inline-flex size-10 cursor-pointer items-center justify-center rounded-full border border-ink/15 bg-white text-accent shadow-md hover:bg-highlight-soft"
                >
                  <HelpCircle aria-hidden="true" className="size-5" />
                </button>
              </Popover.Trigger>
            </Tooltip.Trigger>
            <Tooltip.Portal>
              <Tooltip.Content side="top" align="end" sideOffset={8} className={bubble}>
                {ABOUT_PHOEBE}
              </Tooltip.Content>
            </Tooltip.Portal>
          </Tooltip.Root>
          <Popover.Portal>
            <Popover.Content
              side="top"
              align="end"
              sideOffset={8}
              className={bubble}
              aria-label="About Phoebe"
            >
              {ABOUT_PHOEBE}
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
      </Tooltip.Provider>
    </div>
  );
}
