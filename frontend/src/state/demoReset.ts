// Tiny event bus: "Reset my demo" emits, the chat provider (a later task)
// subscribes so the visible conversation clears along with the server data.

const listeners = new Set<() => void>();

export function emitDemoReset(): void {
  for (const listener of [...listeners]) listener();
}

/** Subscribe to demo resets. Returns an unsubscribe function. */
export function onDemoReset(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}
