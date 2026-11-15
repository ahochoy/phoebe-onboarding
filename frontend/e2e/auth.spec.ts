import { demoPassword, expect, loggedIn, resetDemo, submitPassword, test } from "./fixtures";

test("wrong password then right password", async ({ page }) => {
  await page.goto("/");
  const field = page.getByLabel("Demo password");

  await submitPassword(page, "definitely-not-the-password");
  await expect(page.getByRole("alert")).toHaveText("That password didn't work.");
  await expect(field).toBeFocused();
  await expect(field).toHaveAttribute("aria-invalid", "true");
  await expect(page).toHaveURL(/\/$/);

  await submitPassword(page, demoPassword());
  await expect(page).toHaveURL(/\/employee$/);
  await expect(page.getByRole("dialog", { name: /Welcome to the .* team/ })).toBeVisible();
  await resetDemo(page);
});

test("reload stays logged in", async ({ page }) => {
  await loggedIn(page);
  await page.reload();
  await expect(page).toHaveURL(/\/employee$/);
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
  await expect(page.getByLabel("Demo password")).toHaveCount(0);
  // The welcome splash is once per login, not per page load.
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("logout returns to landing", async ({ page }) => {
  await loggedIn(page);
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByLabel("Demo password")).toBeVisible();

  // The session is gone: the employee page sends us back.
  await page.goto("/employee");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByLabel("Demo password")).toBeVisible();
});
