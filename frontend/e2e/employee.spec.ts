import type { Page } from "@playwright/test";
import { expect, loggedIn, openAdminTab, pickGroup, showPanel, test } from "./fixtures";

const PROGRESS = /^(\d+) of (\d+) done$/;

function readCount(text: string | null): { done: number; total: number } {
  const m = PROGRESS.exec(text?.trim() ?? "");
  if (!m) throw new Error(`no progress count in ${JSON.stringify(text)}`);
  return { done: Number(m[1]), total: Number(m[2]) };
}

function alexProgress(page: Page) {
  return page
    .getByRole("table", { name: "People and onboarding progress" })
    .getByRole("row")
    .filter({ has: page.getByRole("button", { name: "Alex Rivera" }) })
    .getByText(PROGRESS);
}

// The one cross-view journey: an admin's new task reaches the employee checklist, and
// checking it moves the employee's count and the admin's People table together.
test(
  "admin adds a Platform task, the employee checks it, and both counts go up",
  {
    tag: "@journey",
  },
  async ({ page }) => {
    await loggedIn(page);
    const title = "Read the Platform runbook";

    await openAdminTab(page, "Tasks");
    await page.getByRole("button", { name: "Add task" }).click();
    const dialog = page.getByRole("dialog", { name: "Add task" });
    await dialog.getByLabel("Title").fill(title);
    await pickGroup(page, dialog, "Platform");
    await dialog.getByRole("button", { name: "Add", exact: true }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByRole("heading", { name: title })).toBeVisible();

    await page.getByRole("radio", { name: "Employee" }).click();
    await expect(page).toHaveURL(/\/employee$/);
    await showPanel(page, "Tasks");
    const box = page.getByRole("checkbox", { name: title });
    // Once the new task is on the checklist, the count includes it.
    await expect(box).not.toBeChecked();
    const progress = page.getByRole("region", { name: "Tasks" }).getByText(PROGRESS);
    await expect(progress).toHaveText(PROGRESS);
    const before = readCount(await progress.textContent());

    await box.click();
    await expect(box).toBeChecked();
    await expect(progress).toHaveText(`${before.done + 1} of ${before.total} done`);

    // The admin table may show a cached count first; the retrying assertion waits for
    // its refetch to agree with the employee view.
    await openAdminTab(page, "People & Progress");
    await expect(alexProgress(page)).toHaveText(`${before.done + 1} of ${before.total} done`);
  },
);
