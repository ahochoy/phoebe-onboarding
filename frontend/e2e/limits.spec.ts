import {
  ask,
  citationButtons,
  composer,
  expect,
  loggedIn,
  setControl,
  showPanel,
  test,
} from "./fixtures";

const PILL = "Rate limit exceeded. Please wait for sessions to refresh.";
const OFFLINE = "The Phoebe demo is temporarily offline. Please check back later.";

// The kill switch is global to the stack: these run one at a time and always reopen.
test.describe.configure({ mode: "serial" });

test.beforeAll(async () => {
  await setControl("open");
});

test.afterAll(async () => {
  await setControl("open");
});

test("make pause shows the pill, disables chat, and leaves tasks working", async ({ page }) => {
  await loggedIn(page);
  await setControl("pause");
  await page.reload();

  await expect(page.getByRole("button", { name: PILL, exact: true })).toBeVisible();
  await showPanel(page, "Chat");
  await expect(composer(page)).toBeDisabled();

  await showPanel(page, "Tasks");
  const progress = page.getByRole("region", { name: "Tasks" }).getByText(/^\d+ of \d+ done$/);
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
  // Still checked after a reload, so the server kept it.
  await page.reload();
  await showPanel(page, "Tasks");
  await expect(box).toBeChecked();
});

test("make kill shows the offline copy on the landing page", async ({ page }) => {
  await setControl("kill");
  await page.goto("/");
  await expect(page.getByText(OFFLINE)).toBeVisible();
  await expect(page.getByLabel("Demo password")).toHaveCount(0);
});

test("make open restores normal behaviour", async ({ page }) => {
  await setControl("open");
  await page.goto("/");
  await expect(page.getByText(OFFLINE)).toHaveCount(0);
  await loggedIn(page);

  await expect(page.getByRole("button", { name: PILL })).toHaveCount(0);
  await showPanel(page, "Chat");
  await expect(composer(page)).toBeEnabled();
  const answer = await ask(page, "How many PTO days do I get?");
  await expect(citationButtons(answer).first()).toBeVisible();
});
