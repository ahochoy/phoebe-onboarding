import { composer, expect, loggedIn, setControl, showPanel, test } from "./fixtures";

const PILL = "Rate limit exceeded. Please wait for sessions to refresh.";
const BANNER =
  "Chat and uploads are paused to keep this demo within its spending limit. Everything else works as usual.";
const OFFLINE = "The Phoebe demo is temporarily offline. Please check back later.";

// The kill switch is global to the stack, so this runs alone, after every other test,
// in one browser (playwright.config.ts). The UI for each state is covered by
// StatusPill/ChatPanel/Landing component tests and the API by test_api_limits.py; this
// checks that the real `make pause|kill|open` reaches the browser.
test.afterEach(async () => {
  await setControl("open");
});

test("make pause, kill and open reach the UI", { tag: "@once" }, async ({ page }) => {
  await loggedIn(page);

  // Pause: the spend banner shows (not the rate-limit pill), chat is disabled, tasks
  // still save.
  await setControl("pause");
  await page.reload();
  await expect(page.getByText(BANNER)).toBeVisible();
  await expect(page.getByRole("button", { name: PILL })).toHaveCount(0);
  await showPanel(page, "Chat");
  await expect(composer(page)).toBeDisabled();

  await showPanel(page, "Tasks");
  const progress = page.getByRole("region", { name: "Tasks" }).getByText(/^\d+ of \d+ done$/);
  await expect(progress).toBeVisible();
  const [done, total] = ((await progress.textContent()) ?? "").split(/\D+/).map(Number);
  const boxId = await page.getByRole("checkbox", { checked: false }).first().getAttribute("id");
  const box = page.locator(`[id="${boxId}"]`);
  // The box checks optimistically, before the PUT is sent; a reload before the response
  // can cancel the save. Wait for the server to take it first.
  const saved = page.waitForResponse(
    (r) => r.request().method() === "PUT" && r.url().endsWith("/completion") && r.ok(),
  );
  await box.click();
  await expect(box).toBeChecked();
  await expect(progress).toHaveText(`${done! + 1} of ${total} done`);
  await saved;
  await page.reload();
  await showPanel(page, "Tasks");
  await expect(box).toBeChecked();

  // Kill: the landing page shows the offline copy and no password field.
  await setControl("kill");
  await page.goto("/");
  await expect(page.getByText(OFFLINE)).toBeVisible();
  await expect(page.getByLabel("Demo password")).toHaveCount(0);

  // Open: everything is back. Drop the session first, as a new visitor would arrive.
  await setControl("open");
  await page.context().clearCookies();
  await page.goto("/");
  await expect(page.getByLabel("Demo password")).toBeVisible();
  await expect(page.getByText(OFFLINE)).toHaveCount(0);
  await loggedIn(page);
  await expect(page.getByText(BANNER)).toHaveCount(0);
  await showPanel(page, "Chat");
  await expect(composer(page)).toBeEnabled();
});
