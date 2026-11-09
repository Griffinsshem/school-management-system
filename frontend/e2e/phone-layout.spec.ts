import { expect, test, type Locator, type Page } from "@playwright/test";

import { problems } from "./axe";
import { call, feeClass, issued, logInAs, offScreen, unique } from "./fees-data";
import { ATTENDANCE_ADMIN_EMAIL } from "./helpers";

// Phone layouts of the polish round (P1): the bill page's payments, the
// subjects list and a class list become one block per row below 40rem
// ("stack-table" in globals.css), so nothing has to be scrolled sideways,
// not even inside its own box. All names, amounts and codes are made up.

const PHONE = { width: 320, height: 740 };
const WIDE_FONT = 'body { font-family: "DejaVu Sans", Verdana, sans-serif !important; }';

function kenyaToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(new Date());
}

// Boxes inside the page that scroll sideways because their content is wider
// than they are (offScreen() allows those; this does not).
async function scrollsSideways(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll("main *"))
      .filter((el) => ["auto", "scroll"].includes(getComputedStyle(el).overflowX))
      .filter((el) => el.scrollWidth > el.clientWidth + 1)
      .map((el) => `${el.tagName.toLowerCase()} is ${el.scrollWidth}px wide in ${el.clientWidth}px`),
  );
}

// The table is shown as blocks: headings hidden, rows as blocks, and each
// cell's column name drawn before it (CSS ::before, which text searches do
// not see). Returns the labels drawn in the first row.
async function stackedLabels(table: Locator): Promise<string[]> {
  return table.evaluate((t) => {
    const head = t.querySelector("thead");
    const row = t.querySelector("tbody > tr");
    if (!row || (head && getComputedStyle(head).display !== "none") || getComputedStyle(row).display !== "block") {
      return [];
    }
    return Array.from(row.children).map((cell) => getComputedStyle(cell, "::before").content.replace(/^"|"$/g, ""));
  });
}

async function fitsAPhone(page: Page, what: string) {
  await page.addStyleTag({ content: WIDE_FONT });
  expect(await offScreen(page), what).toEqual([]);
  expect(await scrollsSideways(page), what).toEqual([]);
}

// A billed class with three payments on Amani's bill: a bank payment with
// the longest reference and payer's name, a second large payment (so the
// balance reads "KES 1,983,000 credit") and a cancelled cash payment.
async function billWithPayments(page: Page) {
  const f = await feeClass(page, { widest: true });
  const bills = await issued(page, f);
  const pay = async (body: Record<string, unknown>) => {
    const made = await call(page, "POST", `/school/fees/bills/${bills.Amani}/payments`, {
      paid_on: kenyaToday(),
      ...body,
    });
    expect(made.status, JSON.stringify(made.json)).toBe(201);
    return made.json.payment as { id: string; receipt_number: number };
  };
  const kept = await pay({
    amount_kes: 1_000_000,
    method: "bank",
    reference: `B${unique()}`.padEnd(40, "R"),
    paid_by: `P${"a".repeat(99)}`,
  });
  await pay({ amount_kes: 1_000_000, method: "cash" });
  const gone = await pay({ amount_kes: 500, method: "cash" });
  const cancel = await call(page, "POST", `/school/fees/payments/${gone.id}/cancellation`, {
    reason: `Typed twice ${"w".repeat(80)}`,
  });
  expect(cancel.status).toBe(201);
  return { f, bills, kept };
}

test("a bill's payments are one block each on a phone, with every detail and button in view", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const { bills, kept } = await billWithPayments(page);
  const number = String(kept.receipt_number).padStart(6, "0");

  await page.setViewportSize(PHONE);
  await page.goto(`/fees/bills/${bills.Amani}`);
  const payments = page.getByRole("region", { name: "Payments" });
  await expect(payments.getByRole("link", { name: `Receipt ${number}` })).toBeVisible();
  expect(await stackedLabels(payments.locator("table"))).toEqual([
    "Receipt: ",
    "Paid on, how: ",
    "Amount: ",
    "Recorded: ",
  ]);
  const lines = page.getByRole("region", { name: "What is owed" }).locator("table");
  expect(await stackedLabels(lines)).toEqual(["none", "Amount: ", "Added: "]);
  await fitsAPhone(page, "bill on a phone");
  const cancel = page.getByRole("button", { name: `Cancel payment ${number}` });
  await cancel.scrollIntoViewIfNeeded();
  await expect(cancel).toBeInViewport({ ratio: 1 });

  // The cancel question opens inside the block and still fits.
  await cancel.click();
  await expect(page.getByRole("form", { name: `Cancel payment ${number}` }).getByLabel("Reason")).toBeFocused();
  await fitsAPhone(page, "cancel question on a phone");

  // Wider screens keep the table with its column headings.
  await page.setViewportSize({ width: 1024, height: 800 });
  await expect(payments.getByRole("columnheader", { name: "Recorded" })).toBeVisible();
  expect(await stackedLabels(payments.locator("table"))).toEqual([]);
});

test("the subjects list is one block per subject on a phone, with its Edit button in view", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  // The longest name the school can enter, as one unbroken word.
  const name = `Agriculture${unique()}`.padEnd(60, "x");
  const made = await call(page, "POST", "/school/subjects", { name, code: `A${unique()}`.slice(0, 10) });
  expect(made.status, JSON.stringify(made.json)).toBe(201);

  await page.setViewportSize(PHONE);
  await page.goto("/subjects");
  await expect(page.getByText("Loading...")).toHaveCount(0);
  expect(await stackedLabels(page.getByRole("table", { name: "Subjects" }))).toEqual([
    "none",
    "Code: ",
    "Status: ",
    "KCSE mean grade: ",
    "none",
  ]);
  await fitsAPhone(page, "subjects on a phone");
  const edit = page.getByRole("button", { name: `Edit ${name}` });
  await edit.scrollIntoViewIfNeeded();
  await expect(edit).toBeInViewport({ ratio: 1 });

  await page.setViewportSize({ width: 1024, height: 800 });
  await expect(page.getByRole("columnheader", { name: "KCSE mean grade" })).toBeVisible();
});

test("a class list is one block per student on a phone, and the Move choice is full width", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const f = await feeClass(page, { widest: true });
  const other = await call(page, "POST", "/school/classes", {
    academic_year_id: f.yearId,
    grade: "grade_7",
    stream: `Z${unique()}`.slice(0, 20),
  });
  expect(other.status).toBe(201);

  await page.setViewportSize(PHONE);
  await page.goto(`/classes/${f.classId}`);
  const list = page.getByRole("table", { name: /^Students in / });
  await expect(list).toContainText(`Amani ${f.id}`);
  expect((await stackedLabels(list)).slice(0, 2)).toEqual(["Admission no.: ", "Name: "]);
  await fitsAPhone(page, "class list on a phone");

  await page.getByRole("button", { name: new RegExp(`^Move Amani ${f.id}`) }).click();
  const choice = page.getByLabel(`Move Amani ${f.id} to`);
  await expect(choice).toBeFocused();
  const box = await choice.boundingBox();
  // Most of the 320 px screen, not a narrow "Choo..." box.
  expect(box?.width ?? 0).toBeGreaterThan(240);
  await fitsAPhone(page, "move choice on a phone");
});

for (const scheme of ["light", "dark"] as const) {
  test(`phone layouts pass the accessibility checks (${scheme})`, async ({ page }) => {
    test.setTimeout(90_000);
    await page.emulateMedia({ colorScheme: scheme });
    await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
    const { f, bills } = await billWithPayments(page);
    await page.setViewportSize(PHONE);
    const found: string[] = [];
    for (const [what, path] of [
      ["bill", `/fees/bills/${bills.Amani}`],
      ["subjects", "/subjects"],
      ["class list", `/classes/${f.classId}`],
    ]) {
      await page.goto(path);
      await expect(page.getByText("Loading...")).toHaveCount(0);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      found.push(...(await problems(page)).map((p) => `${what}: ${p}`));
    }
    expect(found).toEqual([]);
  });
}
