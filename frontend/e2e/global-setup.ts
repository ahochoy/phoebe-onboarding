import { setControl } from "./fixtures";

/**
 * The kill switch lives in the stack and outlives a run. If a run stops inside
 * limits.spec.ts (Ctrl-C, CI timeout), its afterAll never reopens it, and every login in
 * the next run would fail. Reopen it before any test; vite preview is already up here.
 */
export default async function globalSetup(): Promise<void> {
  await setControl("open");
}
