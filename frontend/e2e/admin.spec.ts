import { fileURLToPath } from "node:url";
import { expect, loggedIn, openAdminTab, pickGroup, showPanel, test } from "./fixtures";

const WELCOME_MD = fileURLToPath(new URL("./files/welcome.md", import.meta.url));

// The only test of the real worker indexing a browser multipart upload, then serving the
// result back to the employee view.
test(
  "an uploaded Markdown file is indexed and opens from the employee Documents panel",
  {
    tag: "@once",
  },
  async ({ page }) => {
    await loggedIn(page);
    const title = "Platform welcome notes";
    await openAdminTab(page, "Documents");
    await page.getByRole("button", { name: "Upload document" }).click();

    const dialog = page.getByRole("dialog", { name: "Upload a document" });
    await dialog.getByLabel("File").setInputFiles(WELCOME_MD);
    await dialog.getByLabel("Title").fill(title);
    await pickGroup(page, dialog, "Platform");
    await dialog.getByRole("button", { name: "Upload" }).click();
    await expect(dialog).toBeHidden();

    const row = page.getByRole("listitem").filter({ has: page.getByText(title, { exact: true }) });
    await expect(row.getByText("Indexed ✓")).toBeVisible({ timeout: 30_000 });

    await page.getByRole("radio", { name: "Employee" }).click();
    await showPanel(page, "Docs");
    const docs = page.getByRole("region", { name: "Documents" });
    // The row's name is "<type> <title> <purpose> Updated <date>".
    await docs.getByRole("button", { name: `Markdown ${title}` }).click();
    const viewer = page.getByRole("dialog", { name: title });
    await expect(viewer.getByText("Our team standup is at 9:30")).toBeVisible();
  },
);
