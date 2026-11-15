import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { test as base, expect, type Locator, type Page } from "@playwright/test";
import { PREVIEW_URL } from "./preview";

export { expect };

/**
 * Every test also wipes its sandbox when it ends (best effort; a 401 just means it never
 * logged in). Leftover visitor rows would otherwise pile up in the stack's database, and
 * a visitor document in a seed group makes the next `make stack` reseed fail.
 */
export const test = base.extend<{ wipeSandbox: void }>({
  wipeSandbox: [
    async ({ page }, use) => {
      await use();
      await page.request
        .post("/api/reset", { headers: { "X-Phoebe-Csrf": "1" } })
        .catch(() => undefined);
    },
    { auto: true },
  ],
});

const repoRoot = fileURLToPath(new URL("../..", import.meta.url));

/** The demo password comes from the environment only (`make e2e` exports the Makefile default). */
export function demoPassword(): string {
  const value = process.env.PHOEBE_DEV_PASSWORD;
  if (!value) throw new Error("Set PHOEBE_DEV_PASSWORD (make e2e exports it).");
  return value;
}

/** Below the lg breakpoint the employee page shows one panel at a time behind bottom tabs. */
export function isNarrow(page: Page): boolean {
  return (page.viewportSize()?.width ?? 1280) < 1024;
}

/** Fill the landing form and submit. Does not wait for the result. */
export async function submitPassword(page: Page, password: string): Promise<void> {
  await page.getByLabel("Demo password").fill(password);
  await page.getByRole("button", { name: "Enter" }).click();
}

/** Posts /api/reset with the CSRF header, using the page's session cookie. */
export async function resetDemo(page: Page): Promise<void> {
  const res = await page.request.post("/api/reset", { headers: { "X-Phoebe-Csrf": "1" } });
  expect(res.status(), "POST /api/reset").toBe(204);
}

/**
 * Logs in through the landing page, closes the welcome splash, resets the sandbox and
 * reloads, leaving the employee page ready.
 */
export async function loggedIn(page: Page): Promise<void> {
  await page.goto("/");
  await submitPassword(page, demoPassword());
  const throttled = page.getByRole("alert").filter({ hasText: "Rate limit exceeded" });
  const welcome = page.getByRole("dialog", { name: /Welcome to the/ });
  await expect(welcome.or(throttled)).toBeVisible();
  if (await throttled.isVisible()) {
    throw new Error("Login was throttled: start the stack with `make stack-e2e`.");
  }
  await welcome.getByRole("button", { name: "Got it" }).click();
  await expect(welcome).toBeHidden();
  await resetDemo(page);
  await page.reload();
  await expect(page).toHaveURL(/\/employee$/);
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
}

/** On narrow screens, picks the bottom tab for a panel; a no-op at lg and up. */
export async function showPanel(page: Page, name: "Tasks" | "Chat" | "Docs"): Promise<void> {
  if (!isNarrow(page)) return;
  const tab = page.getByRole("tablist", { name: "Sections" }).getByRole("tab", { name });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-selected", "true");
}

export function composer(page: Page): Locator {
  return page.getByRole("textbox", { name: "Ask Phoebe a question" });
}

export function lastAnswer(page: Page): Locator {
  return page.locator('[data-role="assistant"]').last();
}

/**
 * Waits for the latest answer to settle: cited (a Sources list), refused (Closest
 * documents) or failed. Citation buttons only render once an answer has settled.
 */
export async function settledAnswer(page: Page): Promise<Locator> {
  const answer = lastAnswer(page);
  await expect(answer).toBeVisible();
  await expect(answer.getByText("Phoebe is thinking…")).toBeHidden({ timeout: 30_000 });
  // A failed answer is a `.text-danger` line; the spec's next assertion then fails clearly.
  await expect(
    answer.getByText(/^(Sources|Closest documents)$/).or(answer.locator(".text-danger")),
  ).toBeVisible({ timeout: 30_000 });
  return answer;
}

/** Types a question into the composer and sends it with Enter. */
export async function ask(page: Page, question: string): Promise<Locator> {
  const box = composer(page);
  await box.fill(question);
  await box.press("Enter");
  await expect(page.locator('[data-role="user"]').last()).toHaveText(question);
  return settledAnswer(page);
}

export function citationButtons(scope: Locator | Page): Locator {
  return scope.getByRole("button", { name: /^Source \d+: / });
}

type ControlState = "pause" | "kill" | "open";
const EXPECTED: Record<ControlState, string> = {
  pause: "chat_paused",
  kill: "closed",
  open: "open",
};

/**
 * Flips the stack's kill switch with `make pause|kill|open`, then waits until the API
 * reports the new state (it caches the switch for a few seconds).
 */
export async function setControl(state: ControlState): Promise<void> {
  execFileSync("make", [state], { cwd: repoRoot, stdio: "pipe", env: process.env });
  await expect
    .poll(
      async () => {
        const res = await fetch(new URL("/api/status", PREVIEW_URL));
        const body = (await res.json()) as { state?: string };
        return body.state;
      },
      { timeout: 20_000, intervals: [250, 500, 1000] },
    )
    .toBe(EXPECTED[state]);
}
