import { Dialog } from "radix-ui";
import { useState } from "react";
import type { Me } from "../api/types";
import { PhoebeArt } from "./PhoebeArt";

export const WELCOME_KEY = "phoebe.welcome";

function readFlag(): string | null {
  try {
    return window.sessionStorage.getItem(WELCOME_KEY);
  } catch {
    return null;
  }
}

function writeFlag(value: string): void {
  try {
    window.sessionStorage.setItem(WELCOME_KEY, value);
  } catch {
    // Blocked storage only means the splash may show again; harmless.
  }
}

/** Shown once, right after a login in this tab (never for a restored session). */
export function WelcomeSplash({ me }: { me: Me }) {
  const [open, setOpen] = useState(() => readFlag() === "pending");
  const first = me.name.split(/\s+/)[0] ?? me.name;

  function close() {
    writeFlag("done");
    setOpen(false);
  }

  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && close()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/50" />
        <Dialog.Content className="fixed top-1/2 left-1/2 z-50 flex w-[min(26rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-3 rounded-lg bg-white p-8 text-center shadow-xl">
          <PhoebeArt
            pose="onboarding-checklist"
            size={160}
            className="motion-safe:animate-bounce"
          />
          <Dialog.Title className="text-xl font-semibold">
            {`Welcome to the ${me.team_name} team, ${first}!`}
          </Dialog.Title>
          <Dialog.Description className="text-sm">
            Phoebe can answer questions about your team, your tasks and the documents you have been
            given.
          </Dialog.Description>
          <button
            type="button"
            onClick={close}
            className="mt-2 inline-flex min-h-8 cursor-pointer items-center rounded-md bg-accent px-4 py-1 text-sm font-medium text-white"
          >
            Got it
          </button>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
