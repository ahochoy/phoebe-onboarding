import AxeBuilder from "@axe-core/playwright";
import type { Locator, Page } from "@playwright/test";
import {
  ask,
  citationButtons,
  composer,
  demoPassword,
  expect,
  isNarrow,
  loggedIn,
  resetDemo,
  settledAnswer,
  showPanel,
  test,
} from "./fixtures";

const TAGS = ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"];

async function expectNoViolations(page: Page): Promise<void> {
  const { violations } = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  // Summarise so a failure says which rule and which nodes, not just "not equal".
  const summary = violations.map((v) => ({
    id: v.id,
    help: v.help,
    nodes: v.nodes.map((n) => n.target.join(" ")),
  }));
  expect(summary).toEqual([]);
}

/**
 * Presses Tab until one of `target`'s elements has focus. Safari's Tab skips buttons and
 * links unless "Press Tab to highlight each item" is on; Option+Tab is its every-item Tab.
 */
async function tabTo(page: Page, target: Locator, max = 80, back = false): Promise<void> {
  const webkit = page.context().browser()?.browserType().name() === "webkit";
  const key = `${webkit ? "Alt+" : ""}${back ? "Shift+" : ""}Tab`;
  for (let i = 0; i < max; i++) {
    await page.keyboard.press(key);
    const hit = await target.evaluateAll((els) =>
      els.includes(document.activeElement as HTMLElement),
    );
    if (hit) return;
  }
  throw new Error(`Tab never reached ${target.toString()}`);
}

test.describe("axe", () => {
  test("landing", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByLabel("Demo password")).toBeVisible();
    await expectNoViolations(page);
  });

  test("employee", async ({ page }) => {
    await loggedIn(page);
    await expect(page.getByText(/^\d+ of \d+ done$/)).toBeAttached();
    await expect(page.getByRole("button", { name: "How many PTO days do I get?" })).toBeAttached();
    await expectNoViolations(page);
  });

  test("document viewer open", async ({ page }) => {
    await loggedIn(page);
    await showPanel(page, "Chat");
    const answer = await ask(page, "How many PTO days do I get?");
    await citationButtons(answer).first().click();
    const viewer = page.getByRole("dialog");
    await expect(viewer.locator("mark").first()).toBeVisible();
    await expectNoViolations(page);
  });

  for (const tab of ["Home", "People & Progress", "Documents", "Tasks", "Groups"]) {
    test(`admin ${tab}`, async ({ page }) => {
      await loggedIn(page);
      await page.getByRole("radio", { name: "Admin" }).click();
      await page.getByRole("tab", { name: tab }).click();
      const panel = page.getByRole("tabpanel", { name: tab });
      await expect(panel.getByRole("heading", { level: 2 })).toBeVisible();
      await expect(panel.getByRole("status")).toHaveCount(0); // finished loading
      await expectNoViolations(page);
    });
  }
});

test("keyboard only: log in, check a task, ask, open a citation, Escape returns focus", async ({
  page,
}) => {
  test.skip(isNarrow(page), "Phones have no Tab key; the bottom-tab layout is covered in mobile.");
  await page.goto("/");
  const field = page.getByLabel("Demo password");
  await expect(field).toBeVisible();

  await tabTo(page, field);
  await page.keyboard.type(demoPassword());
  await tabTo(page, page.getByRole("button", { name: "Enter" }));
  await page.keyboard.press("Enter");

  const welcome = page.getByRole("dialog", { name: /Welcome to the/ });
  await expect(welcome).toBeVisible();
  await expect(welcome.getByRole("button", { name: "Got it" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(welcome).toBeHidden();
  await resetDemo(page);

  const unchecked = page.getByRole("checkbox", { checked: false });
  await tabTo(page, unchecked);
  const boxId = await page.evaluate(() => document.activeElement?.id ?? "");
  await page.keyboard.press("Space");
  await expect(page.locator(`[id="${boxId}"]`)).toBeChecked();

  await tabTo(page, page.getByRole("button", { name: "How many PTO days do I get?" }));
  await page.keyboard.press("Enter");
  const answer = await settledAnswer(page);

  // The suggestion button unmounted when the question was sent, so focus fell to <body>,
  // where each engine resumes Tab from a different place. Start from the composer
  // instead; the answer's sources sit just before it.
  await composer(page).focus();
  await tabTo(page, citationButtons(answer), 40, true);
  // Tag the focused one: an answer can cite the same source twice, so its name may repeat.
  await page.evaluate(() => document.activeElement?.setAttribute("data-e2e-cite", ""));
  const cite = answer.locator("[data-e2e-cite]");
  await page.keyboard.press("Enter");
  const viewer = page.getByRole("dialog");
  await expect(viewer.locator("mark").first()).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(viewer).toBeHidden();
  await expect(cite).toBeFocused();
});
