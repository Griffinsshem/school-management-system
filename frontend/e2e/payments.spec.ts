import { expect, test, type Page } from "@playwright/test";

import { problems } from "./axe";
import { call, feeClass, issued, logInAs, logOut, menu, offScreen, unique } from "./fees-data";
import { ATTENDANCE_ADMIN_EMAIL, ATTENDANCE_TEACHER_EMAIL, FINANCE_EMAIL } from "./helpers";

// Fee payments, receipts and cancellations (E2), in E2E School C. Each test
// bills a class of its own (see fees-data.ts), and makes its own M-Pesa
// codes, so tests never meet each other's payments. Receipt numbers are
// shared by the whole school, so tests read them rather than assume them.
// All names, amounts and codes are made up.

type Payment = { id: string; receipt_number: number };

// A made-up M-Pesa code: 10 capital letters and digits, unique to this run.
function mpesaCode(): string {
  return `T${unique()}`.toUpperCase().replace(/[^A-Z0-9]/g, "").padEnd(10, "X").slice(0, 10);
}

function kenyaToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(new Date());
}

function receiptLabel(n: number): string {
  return `Receipt ${String(n).padStart(6, "0")}`;
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

function form(page: Page) {
  return page.getByRole("form", { name: "Record a payment" });
}

function totals(page: Page) {
  return page.getByRole("table", { name: "Bill lines" });
}

test("a logged-out visitor is sent to the login page", async ({ page }) => {
  for (const path of ["/fees/payments", "/fees/receipts/a"]) {
    await page.goto(path);
    await expect(page).toHaveURL(`/login?next=${encodeURIComponent(path)}`);
  }
});

test("a finance officer records an M-Pesa payment and opens its receipt", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const f = await feeClass(page);
  const bills = await issued(page, f);
  await logOut(page);
  await logInAs(page, FINANCE_EMAIL);
  await page.goto(`/fees/bills/${bills.Amani}`);
  await expect(page.getByText("No payments recorded yet.")).toBeVisible();

  const code = mpesaCode();
  await form(page).getByLabel("Amount received (KES)").fill("10,000");
  await expect(form(page).getByLabel("How it was paid")).toHaveValue("mpesa");
  await form(page).getByLabel("M-Pesa transaction code").fill(code.toLowerCase());
  await expect(form(page).getByLabel("Date paid")).toHaveValue(kenyaToday());
  await form(page).getByLabel("Payer's name (optional)").fill(`Wanjiru ${f.id}`);
  await form(page).getByRole("button", { name: "Record payment" }).click();

  const notice = page.getByRole("status").filter({ hasText: "Payment of KES 10,000 recorded" });
  await expect(notice).toBeVisible();
  await expect(totals(page).getByRole("row", { name: /^Paid/ })).toContainText("KES 10,000");
  await expect(totals(page).getByRole("row", { name: /^Balance/ })).toContainText("KES 7,000");
  const payments = page.getByRole("table", { name: "Payments on this bill" });
  await expect(payments).toContainText(code);
  await expect(payments).toContainText(`Paid by Wanjiru ${f.id}`);
  // Finance officers record but do not cancel (decision of 2026-11-06).
  await expect(page.getByRole("button", { name: /^Cancel payment/ })).toHaveCount(0);
  // The form is empty again, ready for the next payment.
  await expect(form(page).getByLabel("Amount received (KES)")).toHaveValue("");

  await notice.getByRole("link", { name: /^View receipt/ }).click();
  const receipt = page.getByRole("article", { name: /^Receipt \d{6}$/ });
  await expect(receipt).toContainText("E2E School C");
  await expect(receipt).toContainText(`Amani ${f.id}`);
  await expect(receipt).toContainText("KES 10,000");
  await expect(receipt).toContainText(`M-Pesa, ${code}`);
  await expect(receipt).toContainText(`Received fromWanjiru ${f.id}`);
  await expect(receipt).toContainText("KES 7,000 still owed");
  await expect(receipt).not.toContainText("CANCELLED");

  // Printed alone: no band, menu, buttons or back link; dark text on white.
  await page.emulateMedia({ media: "print", colorScheme: "dark" });
  await expect(page.getByRole("banner")).toBeHidden();
  await expect(page.getByRole("button", { name: "Print" })).toBeHidden();
  await expect(page.getByRole("link", { name: /^Back to/ })).toBeHidden();
  await expect(receipt).toBeVisible();
  expect(await page.evaluate(() => getComputedStyle(document.body).color)).toBe("rgb(23, 23, 23)");
});

test("wrong payments are explained before anything is sent, and a used code is refused", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const f = await feeClass(page);
  const bills = await issued(page, f);
  const used = mpesaCode();
  await pay(page, bills.Baraka, { method: "mpesa", reference: used, amount_kes: 500 });
  await page.goto(`/fees/bills/${bills.Amani}`);

  const sent: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/payments")) {
      sent.push(request.url());
    }
  });
  await form(page).getByLabel("Amount received (KES)").fill("0");
  await form(page).getByLabel("M-Pesa transaction code").fill("ABC");
  await form(page).getByLabel("Date paid").fill("2099-01-01");
  await form(page).getByRole("button", { name: "Record payment" }).click();
  const error = form(page).getByRole("alert");
  await expect(error).toContainText("Enter an amount above 0.");
  await expect(error).toContainText("10 letters and digits");
  await expect(error).toContainText("The date paid cannot be in the future.");
  expect(sent).toEqual([]);

  // Bank and cheque ask for their own reference; cash asks for none.
  await form(page).getByLabel("How it was paid").selectOption("bank");
  await expect(form(page).getByLabel("Bank reference")).toBeVisible();
  await form(page).getByLabel("How it was paid").selectOption("cash");
  await expect(form(page).getByLabel(/reference|code|number/i)).toHaveCount(0);

  // The same M-Pesa code twice is refused by the server, in plain words.
  await form(page).getByLabel("How it was paid").selectOption("mpesa");
  await form(page).getByLabel("Amount received (KES)").fill("1000");
  await form(page).getByLabel("M-Pesa transaction code").fill(used);
  await form(page).getByLabel("Date paid").fill(kenyaToday());
  await form(page).getByRole("button", { name: "Record payment" }).click();
  await expect(error).toHaveText(/^This M-Pesa code has already been recorded for a payment in this school\./);
  await expect(page.getByText("No payments recorded yet.")).toBeVisible();
});

test("an administrator cancels a payment with a reason; it stays listed", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const f = await feeClass(page);
  const bills = await issued(page, f);
  const first = await pay(page, bills.Amani, { amount_kes: 10_000 });
  await pay(page, bills.Amani, { amount_kes: 2_000 });
  await page.goto(`/fees/bills/${bills.Amani}`);
  await expect(totals(page).getByRole("row", { name: /^Balance/ })).toContainText("KES 5,000");

  const number = String(first.receipt_number).padStart(6, "0");
  await page.getByRole("button", { name: `Cancel payment ${number}` }).click();
  const confirm = page.getByRole("form", { name: `Cancel payment ${number}` });
  await expect(confirm.getByLabel("Reason")).toBeFocused();
  await confirm.getByRole("button", { name: "Keep it" }).click();
  await expect(confirm).toHaveCount(0);

  await page.getByRole("button", { name: `Cancel payment ${number}` }).click();
  await confirm.getByRole("button", { name: "Yes, cancel payment" }).click();
  await expect(confirm.getByRole("alert")).toHaveText("Enter the reason for cancelling.");
  await confirm.getByLabel("Reason").fill("Entered twice by mistake");
  await confirm.getByRole("button", { name: "Yes, cancel payment" }).click();

  await expect(page.getByRole("status")).toContainText(`Payment ${number} cancelled.`);
  const row = page.getByRole("row", { name: new RegExp(`^${receiptLabel(first.receipt_number)}`) });
  await expect(row).toContainText("Cancelled: Entered twice by mistake");
  await expect(totals(page).getByRole("row", { name: /^Balance/ })).toContainText("KES 15,000");
  await expect(page.getByRole("button", { name: `Cancel payment ${number}` })).toHaveCount(0);

  await row.getByRole("link", { name: receiptLabel(first.receipt_number) }).click();
  const note = page.getByRole("note");
  await expect(note).toContainText("CANCELLED");
  await expect(note).toContainText("Reason: Entered twice by mistake");
});

test("paying more than is owed leaves a credit", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const f = await feeClass(page);
  const bills = await issued(page, f);
  await pay(page, bills.Amani, { amount_kes: 17_500 });
  await page.goto(`/fees/bills/${bills.Amani}`);
  await expect(totals(page).getByRole("row", { name: /^Balance/ })).toContainText("KES 500 credit");
  await page.goto(f.gradePage);
  const amani = page.getByRole("row", { name: new RegExp(`^Amani ${f.id}`) });
  await expect(amani).toContainText("KES 500 credit");
  // Still owed for the grade: Baraka's 17,000; Amani's credit is not taken off it.
  await expect(page.getByRole("row", { name: /^All bills/ })).toContainText(/KES 17,000$/);
});

test("payments on a day add up by method, leaving out cancelled ones", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const before = (await call(page, "GET", `/school/fees/payments?date=${kenyaToday()}`)).json as {
    totals: { method: string; amount_kes: number }[];
    total_kes: number;
  };
  const f = await feeClass(page);
  const bills = await issued(page, f);
  await pay(page, bills.Amani, { amount_kes: 3_000 });
  const code = mpesaCode();
  await pay(page, bills.Baraka, { method: "mpesa", reference: code, amount_kes: 4_000 });
  const mistake = await pay(page, bills.Baraka, { amount_kes: 9_000 });
  expect(
    (await call(page, "POST", `/school/fees/payments/${mistake.id}/cancellation`, { reason: "Wrong student" })).status,
  ).toBe(201);

  await page.goto("/fees");
  await page.getByRole("link", { name: "Payments on a day" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Payments on a day" })).toBeVisible();
  const cash = (before.totals.find((t) => t.method === "cash")?.amount_kes ?? 0) + 3_000;
  const mpesa = (before.totals.find((t) => t.method === "mpesa")?.amount_kes ?? 0) + 4_000;
  const sums = page.getByRole("table", { name: "Totals by how it was paid" });
  await expect(sums.getByRole("row", { name: /^Cash/ })).toContainText(`KES ${cash.toLocaleString("en-KE")}`);
  await expect(sums.getByRole("row", { name: /^M-Pesa/ })).toContainText(`KES ${mpesa.toLocaleString("en-KE")}`);
  await expect(sums.getByRole("row", { name: /^All payments/ })).toContainText(
    `KES ${(before.total_kes + 7_000).toLocaleString("en-KE")}`,
  );
  const list = page.getByRole("table", { name: /^Payments recorded on/ });
  await expect(list.getByRole("row", { name: new RegExp(receiptLabel(mistake.receipt_number)) })).toContainText(
    "Cancelled",
  );
  await expect(list).toContainText(code);

  // Another day shows that day's payments only.
  await page.getByLabel("Day").fill("2026-01-01");
  await page.getByRole("button", { name: "Show" }).click();
  await expect(page).toHaveURL("/fees/payments?date=2026-01-01");
  await expect(page.getByText("No payments were recorded on this day.")).toBeVisible();
});

test("the overview, grade and student pages show what is paid and owed", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const f = await feeClass(page);
  const bills = await issued(page, f);
  await pay(page, bills.Amani, { amount_kes: 4_000 });

  await page.goto(`/fees?year=${f.yearId}&term=1`);
  const grade = page.getByRole("row", { name: /Grade 7 fees/ });
  await expect(grade).toContainText("KES 34,000"); // Billed: two bills of 17,000.
  await expect(grade).toContainText("KES 4,000"); // Paid.
  await expect(grade).toContainText("KES 30,000"); // Outstanding.

  await page.goto(f.gradePage);
  await expect(page.getByRole("row", { name: new RegExp(`^Amani ${f.id}`) })).toContainText("KES 13,000");
  await page.goto(`/students/${f.students.Amani}`);
  await expect(page.getByRole("region", { name: "Fees" })).toContainText("KES 13,000 still owed");
});

test("a teacher has no payment pages", async ({ page }) => {
  await logInAs(page, ATTENDANCE_TEACHER_EMAIL);
  await expect(menu(page).getByRole("link", { name: "Fees", exact: true })).toHaveCount(0);
  for (const path of ["/fees/payments", "/fees/receipts/00000000-0000-0000-0000-000000000000"]) {
    await page.goto(path);
    await expect(page.getByText("You do not have access to this page in E2E School C.")).toBeVisible();
  }
  expect((await call(page, "GET", "/school/fees/payments")).status).toBe(403);
});

// At 320 px with a wide font, the longest stream and admission numbers, and
// the longest bank reference and payer name.
test("payment pages fit a phone screen without sideways scrolling", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const f = await feeClass(page, { widest: true });
  const bills = await issued(page, f);
  const payment = await pay(page, bills.Amani, {
    amount_kes: 1_000_000,
    method: "bank",
    reference: `B${unique()}`.padEnd(40, "R"),
    paid_by: `P${"a".repeat(99)}`,
  });
  await page.setViewportSize({ width: 320, height: 740 });
  for (const path of [`/fees/bills/${bills.Amani}`, `/fees/receipts/${payment.id}`, "/fees/payments"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText("Loading...")).toHaveCount(0);
    await page.addStyleTag({ content: 'body { font-family: "DejaVu Sans", Verdana, sans-serif !important; }' });
    expect(await offScreen(page), path).toEqual([]);
  }
});

for (const scheme of ["light", "dark"] as const) {
  test(`payment pages pass the accessibility checks (${scheme})`, async ({ page }) => {
    test.setTimeout(90_000);
    await page.emulateMedia({ colorScheme: scheme });
    await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
    const f = await feeClass(page);
    const bills = await issued(page, f);
    const kept = await pay(page, bills.Amani, { amount_kes: 1_000 });
    const gone = await pay(page, bills.Amani, { amount_kes: 2_000 });
    await call(page, "POST", `/school/fees/payments/${gone.id}/cancellation`, { reason: "Wrong amount" });
    const found: string[] = [];
    const check = async (state: string) => {
      await expect(page.getByText("Loading...")).toHaveCount(0);
      found.push(...(await problems(page)).map((p) => `${state}: ${p}`));
    };

    await page.goto(`/fees/bills/${bills.Amani}`);
    await expect(page.getByRole("table", { name: "Payments on this bill" })).toBeVisible();
    await check("bill with payments");
    await form(page).getByRole("button", { name: "Record payment" }).click();
    await expect(form(page).getByRole("alert")).toBeVisible();
    await check("payment form with an error");
    const number = String(kept.receipt_number).padStart(6, "0");
    await page.getByRole("button", { name: `Cancel payment ${number}` }).click();
    await check("cancel confirmation");
    await page.goto(`/fees/receipts/${kept.id}`);
    await check("receipt");
    await page.goto(`/fees/receipts/${gone.id}`);
    await check("cancelled receipt");
    await page.goto("/fees/payments");
    await check("payments on a day");
    expect(found).toEqual([]);
  });
}
