import type { Page } from "@playwright/test";
import { expect, loggedIn, showPanel, test } from "./fixtures";

const PROGRESS = /^(\d+) of (\d+) done$/;

function readCount(text: string | null): { done: number; total: number } {
  const m = PROGRESS.exec(text?.trim() ?? "");
  if (!m) throw new Error(`no progress count in ${JSON.stringify(text)}`);
  return { done: Number(m[1]), total: Number(m[2]) };
}

function alexRow(page: Page) {
  return page
    .getByRole("table", { name: "People and onboarding progress" })
    .getByRole("row")
    .filter({ has: page.getByRole("button", { name: "Alex Rivera" }) });
}

test("check a task, the count updates, and Admin People shows Alex's count +1", async ({
  page,
}) => {
  await loggedIn(page);
  const view = page.getByRole("radiogroup", { name: "View" });

  await view.getByRole("radio", { name: "Admin" }).click();
  await page.getByRole("tab", { name: "People & Progress" }).click();
  await expect(page).toHaveURL(/\/admin\/people$/);
  const before = readCount(await alexRow(page).getByText(PROGRESS).textContent());

  await view.getByRole("radio", { name: "Employee" }).click();
  await expect(page).toHaveURL(/\/employee$/);
  await showPanel(page, "Tasks");
  const progress = page.getByRole("region", { name: "Tasks" }).getByText(PROGRESS);
  const mine = readCount(await progress.textContent());
  expect(mine).toEqual(before);

  // Pin the box by id: once checked it would drop out of a `checked: false` query.
  const boxId = await page.getByRole("checkbox", { checked: false }).first().getAttribute("id");
  const box = page.locator(`[id="${boxId}"]`);
  await box.click();
  await expect(box).toBeChecked();
  await expect(progress).toHaveText(`${mine.done + 1} of ${mine.total} done`);

  await view.getByRole("radio", { name: "Admin" }).click();
  await page.getByRole("tab", { name: "People & Progress" }).click();
  await expect(page).toHaveURL(/\/admin\/people$/);
  await expect(alexRow(page).getByText(PROGRESS)).toHaveText(
    `${before.done + 1} of ${before.total} done`,
  );
});
