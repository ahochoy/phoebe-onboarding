import { fileURLToPath } from "node:url";
import type { Locator, Page } from "@playwright/test";
import { expect, loggedIn, showPanel, test } from "./fixtures";

const WELCOME_MD = fileURLToPath(new URL("./files/welcome.md", import.meta.url));

async function openAdminTab(page: Page, name: string): Promise<void> {
  await page.getByRole("radio", { name: "Admin" }).click();
  const tab = page.getByRole("tablist", { name: "Admin sections" }).getByRole("tab", { name });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-selected", "true");
}

async function pickGroup(page: Page, dialog: Locator, group: string): Promise<void> {
  await dialog.getByRole("combobox", { name: "Group" }).click();
  await page.getByRole("option", { name: group, exact: true }).click();
  await expect(dialog.getByRole("combobox", { name: "Group" })).toHaveText(group);
}

test.beforeEach(async ({ page }) => {
  await loggedIn(page);
});

test("an uploaded Markdown file is indexed and shows in the employee Documents panel", async ({
  page,
}) => {
  const title = "Platform welcome notes";
  await openAdminTab(page, "Documents");
  await page.getByRole("button", { name: "Upload document" }).click();

  const dialog = page.getByRole("dialog", { name: "Upload a document" });
  await dialog.getByLabel("File").setInputFiles(WELCOME_MD);
  await dialog.getByLabel("Title").fill(title);
  await pickGroup(page, dialog, "Platform");
  await dialog.getByRole("button", { name: "Upload" }).click();
  await expect(dialog).toBeHidden();

  const row = page
    .getByRole("table", { name: "Documents" })
    .getByRole("row")
    .filter({ has: page.getByRole("cell", { name: title, exact: true }) });
  await expect(row.getByText("Indexed ✓")).toBeVisible({ timeout: 30_000 });

  await page.getByRole("radio", { name: "Employee" }).click();
  await showPanel(page, "Docs");
  const docs = page.getByRole("region", { name: "Documents" });
  // The row's name is "<type> <title> <purpose> Updated <date>".
  await expect(docs.getByRole("button", { name: `Markdown ${title}` })).toBeVisible();
});

test("a task created in Platform shows on the employee checklist", async ({ page }) => {
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
  await showPanel(page, "Tasks");
  await expect(page.getByRole("checkbox", { name: title })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: title })).not.toBeChecked();
});
