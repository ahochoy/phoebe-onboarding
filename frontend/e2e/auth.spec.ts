import { demoPassword, expect, resetDemo, submitPassword, test } from "./fixtures";

// The wrong-password path is covered by Landing.test.tsx and test_api_auth.py. This
// checks what only a real browser can: the session cookie across reload, logout and a
// deep link, in every engine (cookie handling differs between them).
test(
  "log in, reload stays logged in, log out, and a deep link returns to landing",
  {
    tag: "@all",
  },
  async ({ page }) => {
    await page.goto("/");
    await submitPassword(page, demoPassword());
    await expect(page).toHaveURL(/\/employee$/);
    const welcome = page.getByRole("dialog", { name: /Welcome to the .* team/ });
    await expect(welcome).toBeVisible();
    await welcome.getByRole("button", { name: "Got it" }).click();
    await resetDemo(page);

    await page.reload();
    await expect(page).toHaveURL(/\/employee$/);
    await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
    // The welcome splash is once per login, not per page load.
    await expect(page.getByRole("dialog")).toHaveCount(0);

    await page.getByRole("button", { name: "Log out" }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByLabel("Demo password")).toBeVisible();

    // The session is gone: the employee page sends us back.
    await page.goto("/employee");
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByLabel("Demo password")).toBeVisible();
  },
);
