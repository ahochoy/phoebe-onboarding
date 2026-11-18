import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import {
  ask,
  citationButtons,
  expect,
  loggedIn,
  resetDemo,
  showPanel,
  submitPassword,
  test,
} from "../e2e/fixtures";

// README images. Run with `make screenshots`; see docs/development.md.
const HOLIDAYS = "What holidays do we have in November and December?";
const images = (name: string) =>
  fileURLToPath(new URL(`../../docs/images/${name}`, import.meta.url));
const video = fileURLToPath(new URL("../capture-output/demo.webm", import.meta.url));

/** Asks the holiday question and opens the first citation at its highlighted passage. */
async function holidayAnswerWithSource(page: Page): Promise<void> {
  const answer = await ask(page, HOLIDAYS);
  await citationButtons(answer).first().click();
  await expect(page.locator("mark").first()).toBeVisible();
}

test("landing @desktop", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByLabel("Demo password")).toBeVisible();
  await page.screenshot({ path: images("landing.png") });
});

test("employee @desktop", async ({ page }) => {
  await loggedIn(page);
  await page.screenshot({ path: images("employee.png") });
});

test("chat-citations @desktop", async ({ page }) => {
  await loggedIn(page);
  await holidayAnswerWithSource(page);
  await page.screenshot({ path: images("chat-citations.png") });
});

test("mobile @phone", async ({ page }) => {
  await loggedIn(page);
  await showPanel(page, "Chat");
  await ask(page, HOLIDAYS);
  await page.screenshot({ path: images("mobile.png") });
});

test("demo video @desktop", async ({ browser, baseURL }) => {
  const size = { width: 1280, height: 800 };
  // Normal motion: the GIF should show the answer streaming in.
  const context = await browser.newContext({
    baseURL,
    viewport: size,
    reducedMotion: "no-preference",
    recordVideo: { dir: test.info().outputPath("video"), size },
  });
  const page = await context.newPage();
  try {
    await page.goto("/");
    await page.waitForTimeout(800);
    await submitPassword(page, process.env.PHOEBE_DEV_PASSWORD ?? "");
    const welcome = page.getByRole("dialog", { name: /Welcome to the/ });
    await welcome.getByRole("button", { name: "Got it" }).click();
    await resetDemo(page);
    await page.reload();
    await holidayAnswerWithSource(page);
    await page.waitForTimeout(1500);
  } finally {
    await resetDemo(page).catch(() => undefined);
    await context.close();
  }
  await page.video()?.saveAs(video);
});
