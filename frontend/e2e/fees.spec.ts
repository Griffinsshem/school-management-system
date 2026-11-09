import { expect, test, type Page } from "@playwright/test";

import { problems } from "./axe";
import { call, feeClass, issued, logInAs, logOut, menu, offScreen } from "./fees-data";
import {
  ATTENDANCE_ADMIN_EMAIL,
  ATTENDANCE_TEACHER_EMAIL,
  FINANCE_EMAIL,
  errorMessage,
  openRoleAllows,
} from "./helpers";

// School fees (E1): fee structures, issuing bills, optional items,
// adjustments and who sees what, in E2E School C (see marks.spec.ts). Each
// test uses a school year of its own, far in the future, so the bills it
// issues never reach another test's students. All names are made up.

const LEAVE = "You have unsaved changes. Leave this page and lose them?";

function item(page: Page, n: number) {
  return page.getByRole("group", { name: `Item ${n}` });
}

test("a logged-out visitor is sent to the login page", async ({ page }) => {
  for (const path of ["/fees", "/fees/a/1/grade_7", "/fees/bills/a"]) {
    await page.goto(path);
    await expect(page).toHaveURL(`/login?next=${encodeURIComponent(path)}`);
  }
});

test("an administrator sets a grade's fees, issues bills and corrects a bill", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const f = await feeClass(page);

  await menu(page).getByRole("link", { name: "Fees", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Fees" })).toBeVisible();
  await page.getByLabel("School year").selectOption({ label: f.yearName });
  const row = page.getByRole("row", { name: /Grade 7 fees/ });
  await expect(row).toContainText("Not set");
  await expect(row).toContainText("0 of 2");
  await row.getByRole("link", { name: "Grade 7 fees" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Grade 7 fees" })).toBeVisible();
  await item(page, 1).getByLabel("Name").fill("Tuition");
  await item(page, 1).getByLabel("Amount (KES)").fill("15,000");
  await page.getByRole("button", { name: "Add item" }).click();
  await item(page, 2).getByLabel("Name").fill("Boarding");
  await item(page, 2).getByLabel("Amount (KES)").fill("30000");
  await item(page, 2).getByLabel("Optional").check();
  await expect(page.getByText("Compulsory fees per student: KES 15,000")).toBeVisible();
  await page.getByRole("button", { name: "Save fee structure" }).click();
  await expect(page.getByRole("main").getByRole("status")).toHaveText("Fee structure saved.");

  await page.getByRole("button", { name: "Issue bills to 2 students" }).click();
  await page.getByRole("button", { name: "Yes, issue 2 bills" }).click();
  await expect(page.getByRole("main").getByRole("status")).toHaveText("2 bills issued for Term 1.");
  // The structure is now read-only.
  await expect(page.getByRole("button", { name: "Save fee structure" })).toHaveCount(0);
  await expect(page.getByRole("row", { name: /Boarding/ })).toContainText("Optional, added per student");
  await expect(page.getByText(/Bills were first issued on .* by E2E Attendance Admin/)).toBeVisible();
  const amaniRow = page.getByRole("row", { name: new RegExp(`Amani ${f.id}`) });
  await expect(amaniRow).toContainText("KES 15,000");

  await amaniRow.getByRole("link").click();
  await expect(page.getByRole("heading", { level: 1, name: `Bill for Amani ${f.id}` })).toBeVisible();
  const guardians = page.getByRole("region", { name: "Guardians to contact" });
  await expect(guardians).toContainText(`Wanjiru ${f.id}`);
  await expect(guardians.getByRole("link", { name: f.phone })).toHaveAttribute("href", `tel:${f.phone}`);

  await page.getByLabel("Optional item", { exact: true }).selectOption({ label: "Boarding (KES 30,000)" });
  await page.getByRole("button", { name: "Add to bill" }).click();
  await expect(page.getByRole("main").getByRole("status")).toHaveText("Boarding added to the bill.");
  const total = page.getByRole("row", { name: /^Total/ });
  await expect(total).toContainText("KES 45,000");
  await expect(page.getByText("No optional items left to add for Grade 7 this term.")).toBeVisible();

  await page.getByLabel("Amount (KES)").fill("-50000");
  await page.getByLabel("Reason").fill("Bursary from the county");
  await page.getByRole("button", { name: "Save adjustment" }).click();
  await expect(errorMessage(page)).toContainText("it can be reduced by at most KES 45,000");
  await page.getByLabel("Amount (KES)").fill("-5000");
  await page.getByRole("button", { name: "Save adjustment" }).click();
  await expect(page.getByRole("main").getByRole("status")).toHaveText("Adjustment saved.");
  await expect(page.getByRole("row", { name: /Adjustment: Bursary from the county/ })).toContainText("-KES 5,000");
  await expect(total).toContainText("KES 40,000");

  await page.getByRole("link", { name: "Back to Grade 7 fees" }).click();
  await expect(page.getByRole("row", { name: new RegExp(`Amani ${f.id}`) })).toContainText("KES 40,000");
  await expect(page.getByRole("row", { name: /All bills/ })).toContainText("KES 55,000");
});

test("wrong fee items are explained, and unsaved ones are not lost silently", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const f = await feeClass(page);
  await page.goto(f.gradePage);

  await item(page, 1).getByLabel("Name").fill("Tuition");
  await page.getByRole("button", { name: "Save fee structure" }).click();
  await expect(errorMessage(page)).toHaveText("Tuition: Enter an amount.");
  await item(page, 1).getByLabel("Amount (KES)").fill("1500.50");
  await page.getByRole("button", { name: "Add item" }).click();
  await item(page, 2).getByLabel("Name").fill("tuition");
  await item(page, 2).getByLabel("Amount (KES)").fill("100");
  await page.getByRole("button", { name: "Save fee structure" }).click();
  await expect(errorMessage(page)).toHaveText(
    "Tuition: Enter a whole number of shillings, without cents. tuition: another item has the same name.",
  );
  await page.getByRole("button", { name: "Remove item 2" }).click();
  await item(page, 1).getByLabel("Amount (KES)").fill("15000");
  await page.getByRole("button", { name: "Save fee structure" }).click();
  await expect(page.getByRole("main").getByRole("status")).toHaveText("Fee structure saved.");

  // Changed again: bills come from the saved structure, so issuing waits.
  await item(page, 1).getByLabel("Amount (KES)").fill("16000");
  await expect(page.getByText("Save the fee structure before issuing bills.")).toBeVisible();
  await expect(page.getByRole("button", { name: /Issue bills/ })).toHaveCount(0);

  const asked: string[] = [];
  page.once("dialog", async (dialog) => {
    asked.push(dialog.message());
    await dialog.dismiss();
  });
  await page.getByRole("link", { name: "Back to fees" }).click();
  await expect.poll(() => asked).toEqual([LEAVE]);
  await expect(item(page, 1).getByLabel("Amount (KES)")).toHaveValue("16000");
});

test("a finance officer manages fees and sees guardians only on bills", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const f = await feeClass(page);
  const bills = await issued(page, f);
  await logOut(page);

  await logInAs(page, FINANCE_EMAIL);
  await expect(menu(page).getByRole("link", { name: "Fees", exact: true })).toBeVisible();
  await openRoleAllows(page);
  // The home page names the permissions in plain words.
  for (const permission of ["See fees and bills", "Set fees, issue bills and correct them"]) {
    await expect(page.getByRole("main").getByText(permission, { exact: true })).toBeVisible();
  }
  await expect(page.getByRole("main").getByText(/fees\.(read|manage)/)).toHaveCount(0);
  for (const hidden of ["Students", "People", "Classes"]) {
    await expect(menu(page).getByRole("link", { name: hidden, exact: true })).toHaveCount(0);
  }
  await page.goto(f.gradePage);
  await expect(page.getByRole("row", { name: /Tuition/ })).toContainText("KES 15,000");
  await page.getByRole("link", { name: `Amani ${f.id}'s bill` }).click();
  await expect(page.getByRole("region", { name: "Guardians to contact" })).toContainText(`Wanjiru ${f.id}`);
  await page.getByLabel("Amount (KES)").fill("1200");
  await page.getByLabel("Reason").fill("Replaced a lost textbook");
  await page.getByRole("button", { name: "Save adjustment" }).click();
  await expect(page.getByRole("row", { name: /^Total/ })).toContainText("KES 18,200");
  await expect(page.getByRole("row", { name: /Replaced a lost textbook/ })).toContainText("E2E Finance Officer");

  // Nothing beyond the fee pages.
  await page.goto(`/students/${f.students.Amani}`);
  await expect(page.getByText("You do not have access to this page in E2E School C.")).toBeVisible();
  await expect(page.getByText(`Wanjiru ${f.id}`)).toHaveCount(0);
  expect(bills.Baraka).toBeTruthy();
});

test("a teacher has no Fees menu or page", async ({ page }) => {
  await logInAs(page, ATTENDANCE_TEACHER_EMAIL);
  await expect(menu(page).getByRole("link", { name: "Fees", exact: true })).toHaveCount(0);
  await page.goto("/fees");
  await expect(page.getByText("You do not have access to this page in E2E School C.")).toBeVisible();
  const response = await call(page, "GET", "/school/academic-years");
  const yearId = (response.json.academic_years as { id: string }[])[0].id;
  expect((await call(page, "GET", `/school/fees/years/${yearId}/terms/1`)).status).toBe(403);
});

// At 320 px (the narrowest common phone), with a wide font such as some
// computers use instead of Arial, the longest class stream and admission
// numbers, and a reason with a very long word.
test("fee pages fit a phone screen without sideways scrolling", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const f = await feeClass(page, { widest: true });
  const bills = await issued(page, f);
  const adjusted = await call(page, "POST", `/school/fees/bills/${bills.Amani}/adjustments`, {
    amount_kes: -1_000,
    reason: `Bursary, see ${"x".repeat(120)} for the letter`,
  });
  expect(adjusted.status).toBe(201);
  await page.setViewportSize({ width: 320, height: 740 });
  for (const path of [`/fees?year=${f.yearId}&term=1`, f.gradePage, `/fees/bills/${bills.Amani}`]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText("Loading...")).toHaveCount(0);
    await page.addStyleTag({ content: 'body { font-family: "DejaVu Sans", Verdana, sans-serif !important; }' });
    expect(await offScreen(page), path).toEqual([]);
    // Money is never split, and right-aligned in tables so the figures line
    // up; in a table shown as one block per row on phones (P1), the amount
    // follows its label instead.
    const amounts = await page.evaluate(() =>
      Array.from(document.querySelectorAll("main td"))
        .filter((cell) => /KES/.test(cell.textContent ?? ""))
        .map((cell) => {
          const style = getComputedStyle(cell);
          return `${style.display === "block" ? "after its label" : style.textAlign} ${style.whiteSpace}`;
        }),
    );
    expect(amounts.length, path).toBeGreaterThan(0);
    for (const amount of new Set(amounts)) {
      expect(["right nowrap", "after its label nowrap"], path).toContain(amount);
    }
  }
});

for (const scheme of ["light", "dark"] as const) {
  test(`fee pages pass the accessibility checks (${scheme})`, async ({ page }) => {
    test.setTimeout(90_000);
    await page.emulateMedia({ colorScheme: scheme });
    await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
    const f = await feeClass(page);
    const found: string[] = [];
    const check = async (state: string) => {
      await expect(page.getByText("Loading...")).toHaveCount(0);
      found.push(...(await problems(page)).map((p) => `${state}: ${p}`));
    };

    await page.goto(`/fees?year=${f.yearId}&term=1`);
    await expect(page.getByRole("row", { name: /Grade 7 fees/ })).toBeVisible();
    await check("overview");
    await page.goto(f.gradePage);
    await item(page, 1).getByLabel("Name").fill("Tuition");
    await page.getByRole("button", { name: "Save fee structure" }).click();
    await expect(errorMessage(page)).toBeVisible();
    await check("editor with an error");
    await item(page, 1).getByLabel("Amount (KES)").fill("15000");
    await page.getByRole("button", { name: "Save fee structure" }).click();
    await page.getByRole("button", { name: "Issue bills to 2 students" }).click();
    await check("issue confirmation");
    await page.getByRole("button", { name: "Yes, issue 2 bills" }).click();
    await expect(page.getByRole("main").getByRole("status")).toBeVisible();
    await check("issued");
    await page.getByRole("link", { name: `Amani ${f.id}'s bill` }).click();
    await page.getByRole("button", { name: "Save adjustment" }).click();
    await expect(errorMessage(page)).toBeVisible();
    await check("bill with an error");
    expect(found).toEqual([]);
  });
}
