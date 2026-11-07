import { expect, test, type Page } from "@playwright/test";

import { problems } from "./axe";
import { call, feeClass, issued, logInAs, logOut, offScreen, unique } from "./fees-data";
import { ATTENDANCE_ADMIN_EMAIL, ATTENDANCE_TEACHER_EMAIL, FINANCE_EMAIL } from "./helpers";

// Balances from earlier terms, fee statements and printable bills (E3), in
// E2E School C. Each test bills a class of its own for Terms 1 and 2 of a
// school year of its own (see fees-data.ts): 17,000 a term each. All names,
// amounts and codes are made up.

type Payment = { id: string; receipt_number: number };

function kenyaToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(new Date());
}

async function pay(page: Page, billId: string, body: Record<string, unknown>): Promise<Payment> {
  const result = await call(page, "POST", `/school/fees/bills/${billId}/payments`, {
    method: "cash",
    paid_on: kenyaToday(),
    ...body,
  });
  expect(result.status, JSON.stringify(result.json)).toBe(201);
  return result.json.payment as Payment;
}

// Both terms billed: Term 1 and Term 2 bills by first name.
async function twoTerms(page: Page, options: { widest?: boolean } = {}) {
  const f = await feeClass(page, { terms: 2, ...options });
  return { f, term1: await issued(page, f, 1), term2: await issued(page, f, 2) };
}

function totals(page: Page) {
  return page.getByRole("table", { name: "Bill lines" });
}

function row(scope: ReturnType<Page["getByRole"]>, name: string) {
  return scope.getByRole("row", { name: new RegExp(`^${name}`) });
}

function receipt(n: number): string {
  return `receipt ${String(n).padStart(6, "0")}`;
}

async function printedAlone(page: Page) {
  await page.emulateMedia({ media: "print" });
  await expect(page.getByRole("banner")).toBeHidden();
  await expect(page.getByRole("button", { name: /^Print/ })).toBeHidden();
  await expect(page.getByRole("link", { name: /^Back to/ })).toBeHidden();
  await page.emulateMedia({ media: "screen" });
}

test("a logged-out visitor is sent to the login page", async ({ page }) => {
  for (const path of ["/fees/students/a/statement", "/fees/bills/a/print", "/fees/a/1/grade_7/print"]) {
    await page.goto(path);
    await expect(page).toHaveURL(`/login?next=${encodeURIComponent(path)}`);
  }
});

test("a bill shows what is owed from earlier terms and warns before recording", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const { f, term1, term2 } = await twoTerms(page);
  await pay(page, term1.Amani, { amount_kes: 4_000 });
  await logOut(page);
  await logInAs(page, FINANCE_EMAIL);

  await page.goto(`/fees/bills/${term2.Amani}`);
  await expect(row(totals(page), "Balance")).toContainText("KES 17,000");
  await expect(row(totals(page), "From earlier terms")).toContainText("KES 13,000");
  await expect(row(totals(page), "Amount due now")).toContainText("KES 30,000");
  const earlier = `Term 1, ${f.yearName}`;
  await expect(page.getByText("Earlier terms not settled:")).toBeVisible();
  const note = page.getByRole("form", { name: "Record a payment" }).getByRole("note");
  await expect(note).toContainText(`Amani ${f.id} also owes KES 13,000 from earlier terms`);

  // Money meant for Term 1 is recorded on its bill.
  await note.getByRole("link", { name: `Record on the ${earlier} bill` }).click();
  await expect(page).toHaveURL(`/fees/bills/${term1.Amani}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(`Bill for Amani ${f.id}`);
  // Term 1 has nothing earlier.
  await expect(row(totals(page), "From earlier terms")).toHaveCount(0);
  await expect(page.getByRole("form", { name: "Record a payment" }).getByRole("note")).toHaveCount(0);
  await pay(page, term1.Amani, { amount_kes: 13_000 });

  // Settled: Term 2 now owes only its own fees.
  await page.goto(`/fees/bills/${term2.Amani}`);
  await expect(row(totals(page), "Balance")).toContainText("KES 17,000");
  await expect(row(totals(page), "From earlier terms")).toHaveCount(0);
  await expect(row(totals(page), "Amount due now")).toHaveCount(0);
  await expect(page.getByText("Earlier terms not settled:")).toHaveCount(0);
});

test("a credit from an earlier term lowers the amount due now", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const { f, term1, term2 } = await twoTerms(page);
  await pay(page, term1.Baraka, { amount_kes: 22_000 });
  await page.goto(`/fees/bills/${term2.Baraka}`);
  await expect(row(totals(page), "From earlier terms")).toContainText("KES 5,000 credit");
  await expect(row(totals(page), "Amount due now")).toContainText("KES 12,000");
  await expect(page.getByRole("link", { name: `Term 1, ${f.yearName} bill` })).toBeVisible();
  // Nothing is owed earlier, so no warning.
  await expect(page.getByRole("form", { name: "Record a payment" }).getByRole("note")).toHaveCount(0);
});

test("a fee statement lists every charge, payment and cancellation", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const { f, term1, term2 } = await twoTerms(page);
  const adjust = await call(page, "POST", `/school/fees/bills/${term1.Amani}/adjustments`, {
    amount_kes: -3_000,
    reason: "Bursary",
  });
  expect(adjust.status).toBe(201);
  const code = `S${unique()}`.toUpperCase().replace(/[^A-Z0-9]/g, "").padEnd(10, "Y").slice(0, 10);
  const kept = await pay(page, term1.Amani, { amount_kes: 5_000, method: "mpesa", reference: code });
  const gone = await pay(page, term2.Amani, { amount_kes: 500 });
  await call(page, "POST", `/school/fees/payments/${gone.id}/cancellation`, { reason: "Typed twice" });

  // From the student page.
  await page.goto(`/students/${f.students.Amani}`);
  const fees = page.getByRole("region", { name: "Fees" });
  await expect(fees).toContainText("All terms: KES 26,000 still owed");
  await fees.getByRole("link", { name: "Fee statement" }).click();
  await expect(page).toHaveURL(`/fees/students/${f.students.Amani}/statement`);

  const statement = page.getByRole("article", { name: `Fee statement for Amani ${f.id}` });
  await expect(statement).toContainText("E2E School C");
  await expect(statement).toContainText(`Grade 7 ${f.id}`);
  await expect(statement).toContainText("BalanceKES 26,000 still owed");
  const table = statement.getByRole("table", { name: "Charges and payments, oldest first" });
  const rows = table.locator("tbody tr");
  await expect(rows).toHaveCount(8);
  const expected = [
    [/^Tuition/, "KES 15,000", "", "KES 15,000"],
    [/^Activity/, "KES 2,000", "", "KES 17,000"],
    [/^Tuition/, "KES 15,000", "", "KES 32,000"],
    [/^Activity/, "KES 2,000", "", "KES 34,000"],
    [/^Adjustment: Bursary/, "", "KES 3,000", "KES 31,000"],
    [new RegExp(`^Payment, ${receipt(kept.receipt_number)}, M-Pesa ${code}`), "", "KES 5,000", "KES 26,000"],
    [new RegExp(`^Payment, ${receipt(gone.receipt_number)}, Cash`), "", "KES 500", "KES 25,500"],
    [new RegExp(`^Payment cancelled \\(${receipt(gone.receipt_number)}\\): Typed twice`), "KES 500", "", "KES 26,000"],
  ] as const;
  for (const [n, [details, charged, paid, balance]] of expected.entries()) {
    const cells = rows.nth(n).locator("td, th");
    await expect(cells.nth(1)).toHaveText(details);
    await expect(cells.nth(2)).toHaveText(charged);
    await expect(cells.nth(3)).toHaveText(paid);
    await expect(cells.nth(4)).toHaveText(balance);
  }
  await expect(rows.nth(0)).toContainText(`Term 1, ${f.yearName}`);
  await expect(rows.nth(2)).toContainText(`Term 2, ${f.yearName}`);
  await expect(table.locator("tfoot")).toContainText("TotalsKES 31,000KES 5,000KES 26,000");
  // No guardian contacts on paper.
  await expect(statement).not.toContainText(f.phone);
  await printedAlone(page);
  await expect(statement).toBeVisible();

  // A receipt opens from its line.
  await table.getByRole("link", { name: receipt(kept.receipt_number) }).click();
  await expect(page.getByRole("article", { name: /^Receipt \d{6}$/ })).toContainText(code);
});

test("one bill and a whole grade's bills print with everything owed", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const { f, term1, term2 } = await twoTerms(page);
  await pay(page, term1.Baraka, { amount_kes: 20_000 });
  await pay(page, term2.Amani, { amount_kes: 1_000 });
  await logOut(page);
  await logInAs(page, FINANCE_EMAIL);

  await page.goto(`/fees/bills/${term2.Amani}`);
  await page.getByRole("link", { name: "Print bill" }).click();
  await expect(page).toHaveURL(`/fees/bills/${term2.Amani}/print`);
  const term = `Term 2, ${f.yearName}`;
  const amani = page.getByRole("article", { name: `Bill for Amani ${f.id}` });
  await expect(amani).toContainText(`School fees bill, ${term}`);
  await expect(row(amani, `Total for ${term}`)).toContainText("KES 17,000");
  await expect(row(amani, "Paid")).toContainText("KES 1,000");
  await expect(row(amani, `Balance for ${term}`)).toContainText("KES 16,000");
  await expect(row(amani, "From earlier terms")).toContainText("KES 17,000");
  await expect(row(amani, "Amount due now")).toContainText("KES 33,000");
  await expect(amani).toContainText(`Term 1, ${f.yearName}: KES 17,000 owed`);
  await expect(amani).not.toContainText(f.phone);
  await printedAlone(page);

  await page.goto(`/fees/${f.yearId}/2/grade_7`);
  await page.getByRole("link", { name: "Print all bills" }).click();
  await expect(page).toHaveURL(`/fees/${f.yearId}/2/grade_7/print`);
  await expect(page.getByText(`${term}: 2 bills, one per page, class by class.`)).toBeVisible();
  const bills = page.getByRole("article", { name: /^Bill for / });
  await expect(bills).toHaveCount(2);
  const baraka = page.getByRole("article", { name: `Bill for Baraka ${f.id}` });
  await expect(row(baraka, "From earlier terms")).toContainText("KES 3,000 credit");
  await expect(row(baraka, "Amount due now")).toContainText("KES 14,000");
  // One bill per printed page.
  const breaks = await bills.evaluateAll((all) => {
    const style = (el: Element) => getComputedStyle(el).breakAfter;
    return all.map(style);
  });
  expect(breaks).toEqual(["auto", "auto"]);
  await page.emulateMedia({ media: "print" });
  expect(await bills.evaluateAll((all) => all.map((el) => getComputedStyle(el).breakAfter))).toEqual(["page", "auto"]);
  await page.emulateMedia({ media: "screen" });
  await printedAlone(page);
});

test("a grade with no bills yet has nothing to print", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const f = await feeClass(page, { terms: 2 });
  await page.goto(`/fees/${f.yearId}/2/grade_7/print`);
  await expect(page.getByText(`No bills have been issued for Grade 7 in Term 2, ${f.yearName} yet.`)).toBeVisible();
  await expect(page.getByRole("button", { name: "Print all" })).toHaveCount(0);
});

test("a teacher has no statements or printable bills", async ({ page }) => {
  await logInAs(page, ATTENDANCE_TEACHER_EMAIL);
  const none = "00000000-0000-0000-0000-000000000000";
  for (const path of [`/fees/students/${none}/statement`, `/fees/bills/${none}/print`, `/fees/${none}/1/grade_7/print`]) {
    await page.goto(path);
    await expect(page.getByText("You do not have access to this page in E2E School C.")).toBeVisible();
  }
  expect((await call(page, "GET", `/school/fees/students/${none}/statement`)).status).toBe(403);
});

// At 320 px with a wide font, the longest stream and admission numbers, a
// bank reference of 40 characters and the largest amounts.
test("statement and printable bills fit a phone screen without sideways scrolling", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const { f, term1, term2 } = await twoTerms(page, { widest: true });
  await pay(page, term1.Amani, { amount_kes: 1_000_000, method: "bank", reference: `B${unique()}`.padEnd(40, "R") });
  await page.setViewportSize({ width: 320, height: 740 });
  const paths = [
    `/fees/bills/${term2.Amani}`,
    `/fees/bills/${term2.Amani}/print`,
    `/fees/students/${f.students.Amani}/statement`,
    `/fees/${f.yearId}/2/grade_7/print`,
  ];
  for (const path of paths) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText("Loading...")).toHaveCount(0);
    await page.addStyleTag({ content: 'body { font-family: "DejaVu Sans", Verdana, sans-serif !important; }' });
    expect(await offScreen(page), path).toEqual([]);
  }
  // On a phone the statement is a list, so every amount is in view.
  await page.goto(`/fees/students/${f.students.Amani}/statement`);
  const lines = page.getByRole("list", { name: "Charges and payments, oldest first" });
  await expect(lines.getByRole("listitem")).toHaveCount(5);
  await expect(lines.getByRole("listitem").nth(4)).toContainText("Paid or taken off KES 1,000,000");
  await expect(lines.getByRole("listitem").nth(4)).toContainText("Balance KES 966,000 credit");
  await expect(page.getByRole("table", { name: "Charges and payments, oldest first" })).toBeHidden();
  // Printed from a phone: the table only, as on any paper.
  await page.emulateMedia({ media: "print" });
  await expect(lines).toBeHidden();
  await expect(page.getByRole("table", { name: "Charges and payments, oldest first" })).toBeVisible();
  await page.emulateMedia({ media: "screen" });
});

for (const scheme of ["light", "dark"] as const) {
  test(`statement and printable bill pages pass the accessibility checks (${scheme})`, async ({ page }) => {
    test.setTimeout(90_000);
    await page.emulateMedia({ colorScheme: scheme });
    await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
    const { f, term1, term2 } = await twoTerms(page);
    await pay(page, term1.Amani, { amount_kes: 1_000 });
    const gone = await pay(page, term2.Amani, { amount_kes: 2_000 });
    await call(page, "POST", `/school/fees/payments/${gone.id}/cancellation`, { reason: "Wrong amount" });
    const found: string[] = [];
    const check = async (state: string) => {
      await expect(page.getByText("Loading...")).toHaveCount(0);
      found.push(...(await problems(page)).map((p) => `${state}: ${p}`));
    };
    await page.goto(`/fees/bills/${term2.Amani}`);
    await expect(row(totals(page), "Amount due now")).toBeVisible();
    await check("bill with earlier terms");
    await page.goto(`/fees/students/${f.students.Amani}/statement`);
    await check("statement");
    await page.setViewportSize({ width: 320, height: 740 });
    await check("statement on a phone");
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto(`/fees/bills/${term2.Amani}/print`);
    await check("printable bill");
    await page.goto(`/fees/${f.yearId}/2/grade_7/print`);
    await check("printable grade bills");
    expect(found).toEqual([]);
  });
}

