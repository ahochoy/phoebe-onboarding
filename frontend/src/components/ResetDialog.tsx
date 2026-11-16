import { useQueryClient } from "@tanstack/react-query";
import { AlertDialog } from "radix-ui";
import { useState } from "react";
import { apiSend } from "../api/client";
import { messageFor } from "../lib/messages";
import { invalidateAll } from "../session/useMe";
import { emitDemoReset } from "../state/demoReset";

const button =
  "inline-flex min-h-8 cursor-pointer items-center rounded-md px-3 py-1 text-sm font-medium";

export function ResetDialog() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await apiSend("POST", "/api/reset");
      await invalidateAll(queryClient);
      emitDemoReset();
      setOpen(false);
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AlertDialog.Root
      open={open}
      onOpenChange={(next) => {
        if (busy) return;
        setOpen(next);
        if (!next) setError(null);
      }}
    >
      <AlertDialog.Trigger asChild>
        <button type="button" className={`${button} border border-accent/40 text-accent`}>
          Reset my demo
        </button>
      </AlertDialog.Trigger>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 z-40 bg-ink/40" />
        <AlertDialog.Content className="fixed top-1/2 left-1/2 z-50 w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-lg bg-white p-6 shadow-xl">
          <AlertDialog.Title className="text-lg font-semibold">Reset your demo?</AlertDialog.Title>
          <AlertDialog.Description className="mt-2 text-sm">
            This clears your chat and puts the people, documents and tasks back to how they started.
          </AlertDialog.Description>
          {error && (
            <p role="alert" className="mt-3 text-sm text-danger">
              {error}
            </p>
          )}
          <div className="mt-5 flex justify-end gap-2">
            <AlertDialog.Cancel asChild>
              <button type="button" disabled={busy} className={`${button} border border-ink/30`}>
                Cancel
              </button>
            </AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <button
                type="button"
                disabled={busy}
                className={`${button} bg-accent text-white disabled:opacity-60`}
                onClick={(e) => {
                  // Keep the dialog open until the reset has finished.
                  e.preventDefault();
                  void confirm();
                }}
              >
                Yes, reset
              </button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
