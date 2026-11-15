import { ask, citationButtons, expect, loggedIn, showPanel, test } from "./fixtures";

const PTO = "How many PTO days do I get?";
const HANDBOOK_CITE = /^Source \d+: Employee Handbook$/;

test.beforeEach(async ({ page }) => {
  await loggedIn(page);
  await showPanel(page, "Chat");
});

test("a cited answer opens the viewer on a highlighted passage", async ({ page }) => {
  const answer = await ask(page, PTO);
  const cites = citationButtons(answer);
  await expect(cites.first()).toBeVisible();

  const label = (await cites.first().getAttribute("aria-label")) ?? "";
  const title = label.replace(/^Source \d+: /, "");
  await cites.first().click();

  const viewer = page.getByRole("dialog", { name: title });
  await expect(viewer).toBeVisible();
  await expect(viewer.locator("mark").first()).toBeVisible();
  await expect(viewer.locator("mark").first()).toBeInViewport();
});

// Another team's documents, outside Alex's groups (company, Engineering, Platform).
const OUTSIDE = /Sales Playbook|East Territory Notes|Payments Runbook/;

/*
 * The brief asks for a refusal with "Closest documents" here. The local stack cannot
 * produce one: its offline extractive model quotes the top passage for any question and
 * the hash embedder's similarities never fall under the refusal threshold, so this
 * question gets an (irrelevant) in-scope citation. A real model refuses it (see
 * backend/scripts/live_chat_check.py). What holds on every backend is the property behind
 * the refusal, checked below; the refusal UI itself is covered by ChatPanel.test.tsx.
 */
test("an out-of-scope question never cites or offers another team's documents", async ({
  page,
}) => {
  const answer = await ask(page, "What's the Sales East quota?");
  await expect(answer.getByRole("button", { name: OUTSIDE })).toHaveCount(0);
  await expect(answer).not.toContainText(OUTSIDE);
});

test("after admin deletes Employee Handbook, the PTO answer cites no Employee Handbook passage", async ({
  page,
}) => {
  // The handbook answers this before the delete, so the check after it means something.
  const first = await ask(page, PTO);
  await expect(first.getByRole("button", { name: HANDBOOK_CITE }).first()).toBeVisible();

  await page.getByRole("radio", { name: "Admin" }).click();
  await page.getByRole("tab", { name: "Documents" }).click();
  await page.getByRole("button", { name: "Delete Employee Handbook" }).click();
  const confirm = page.getByRole("alertdialog", { name: "Delete this document?" });
  await confirm.getByRole("button", { name: "Yes, delete" }).click();
  await expect(confirm).toBeHidden();
  await expect(page.getByRole("button", { name: "Delete Employee Handbook" })).toHaveCount(0);

  await page.getByRole("radio", { name: "Employee" }).click();
  await showPanel(page, "Chat");
  const again = await ask(page, PTO);
  await expect(again.getByRole("button", { name: HANDBOOK_CITE })).toHaveCount(0);
  // Nor does its source list (or a refusal's closest documents) offer the handbook.
  await expect(again.getByRole("button", { name: "Employee Handbook" })).toHaveCount(0);
});
