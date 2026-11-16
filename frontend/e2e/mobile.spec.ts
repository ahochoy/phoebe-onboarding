import { ask, citationButtons, expect, loggedIn, test } from "./fixtures";

// Only the mobile projects run this file (see playwright.config.ts).

test("bottom tabs switch panels and a tapped citation opens a bottom sheet inside the viewport", async ({
  page,
}) => {
  await loggedIn(page);
  const tabs = page.getByRole("tablist", { name: "Sections" });
  await expect(tabs).toBeVisible();

  const tasks = page.getByRole("region", { name: "Tasks" });
  const chat = page.getByRole("region", { name: "Chat" });
  const docs = page.getByRole("region", { name: "Documents" });

  // Chat is the default panel.
  await expect(chat).toBeVisible();
  await expect(tasks).toBeHidden();
  await expect(docs).toBeHidden();

  await tabs.getByRole("tab", { name: "Tasks" }).tap();
  await expect(tasks).toBeVisible();
  await expect(chat).toBeHidden();

  await tabs.getByRole("tab", { name: "Docs" }).tap();
  await expect(docs).toBeVisible();
  await expect(tasks).toBeHidden();

  await tabs.getByRole("tab", { name: "Chat" }).tap();
  await expect(chat).toBeVisible();
  await expect(docs).toBeHidden();

  const answer = await ask(page, "How many PTO days do I get?");
  await citationButtons(answer).first().tap();

  const sheet = page.getByRole("dialog");
  await expect(sheet.locator("mark").first()).toBeVisible();
  // Let the open animation (if any) finish before measuring.
  await expect(async () => {
    const box = await sheet.boundingBox();
    const vp = page.viewportSize();
    expect(box).not.toBeNull();
    expect(vp).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.y).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(vp!.width + 0.5);
    expect(box!.y + box!.height).toBeLessThanOrEqual(vp!.height + 0.5);
    // A bottom sheet: anchored to the bottom edge, full width.
    expect(Math.abs(box!.y + box!.height - vp!.height)).toBeLessThanOrEqual(1);
    expect(box!.width).toBeCloseTo(vp!.width, 0);
  }).toPass({ timeout: 5_000 });
  await expect(sheet.getByRole("button", { name: "Close document" })).toBeInViewport();
});
