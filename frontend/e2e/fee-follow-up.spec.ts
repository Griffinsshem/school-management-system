import { expect, test, type Locator, type Page } from "@playwright/test";

import { problems } from "./axe";
import { call, feeClass, issued, logInAs, logOut, offScreen, unique } from "./fees-data";
import { ATTENDANCE_ADMIN_EMAIL, ATTENDANCE_TEACHER_EMAIL, FINANCE_EMAIL } from "./helpers";

// Pay-by dates and the list of students owing (E4), in E2E School C. Each
// test bills a class of its own. Overdue needs a pay-by date that has
// passed, so those tests use a Grade 1 class in a school year of their own
// in the past (2019 or earlier). All names, phone numbers and amounts are
// made up.

const PHONE = { width: 320, height: 740 };
const WIDE_FONT = 'body { font-family: "DejaVu Sans", Verdana, sans-serif !important; }';

function kenyaToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(new Date());
}

// "14 May 2030", as the pages write dates.
function shown(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeZone: "UTC" }).format(
    new Date(Date.UTC(y, m - 1, d)),
  );
}

// A past school year of the test's own (the first from 2019 down not used
// yet) with Term 1 and a Grade 1 class: Amani (her mother as guardian) and
// Baraka, both billed 17,000, with Term 1's pay-by date on 20 January.
async function pastClass(page: Page) {
  const id = unique();
  const { json } = await call(page, "GET", "/school/academic-years");
  const used = new Set((json.academic_years as { starts_on: string }[]).map((y) => Number(y.starts_on.slice(0, 4))));
  let calendar = 2019;
  while (used.has(calendar)) {
    calendar -= 1;
  }
  const year = await call(page, "POST", "/school/academic-years", {
    name: `Past ${calendar}`,
    starts_on: `${calendar}-01-07`,
    ends_on: `${calendar}-11-22`,
    terms: [{ number: 1, starts_on: `${calendar}-01-07`, ends_on: `${calendar}-04-05` }],
  });
  expect(year.status, JSON.stringify(year.json)).toBe(201);
  const yearId = (year.json.academic_year as { id: string }).id;
  const made = await call(page, "POST", "/school/classes", { academic_year_id: yearId, grade: "grade_1", stream: id });
  expect(made.status).toBe(201);
  const classId = (made.json.class as { id: string }).id;
  const className = `Grade 1 ${id}`;
  const students: Record<string, string> = {};
  for (const [n, first] of ["Amani", "Baraka"].entries()) {
    const student = await call(page, "POST", "/school/students", {
      admission_number: `PS${id}-${n + 1}`,
      full_name: `${first} ${id}`,
    });
    expect(student.status).toBe(201);
    students[first] = (student.json.student as { id: string }).id;
  }
  expect(
    (await call(page, "POST", `/school/classes/${classId}/students`, { student_ids: Object.values(students) })).status,
  ).toBe(201);
  const phone = `+2547${String(Date.now()).slice(-8)}`;
  const guardian = await call(page, "POST", `/school/students/${students.Amani}/guardians`, {
    full_name: `Wanjiru ${id}`,
    phone,
    relationship: "mother",
  });
  expect(guardian.status).toBe(201);
  const grade = `/school/fees/years/${yearId}/terms/1/grades/grade_1`;
  const items = [
    { name: "Tuition", amount_kes: 15_000 },
    { name: "Activity", amount_kes: 2_000 },
  ];
  expect((await call(page, "PUT", grade, { items })).status).toBe(200);
  const result = await call(page, "POST", `${grade}/issue`);
  expect(result.status).toBe(200);
  const bills = Object.fromEntries(
    (result.json.bills as { id: string; student: { id: string } }[]).map((b) => [
      b.student.id === students.Amani ? "Amani" : "Baraka",
      b.id,
    ]),
  );
  const dueOn = `${calendar}-01-20`;
  expect((await call(page, "PUT", `${grade}/due-date`, { due_on: dueOn })).status).toBe(200);
  return { id, calendar, yearId, classId, className, students, phone, bills, dueOn, grade };
}

async function pay(page: Page, billId: string, amount: number) {
  const result = await call(page, "POST", `/school/fees/bills/${billId}/payments`, {
    amount_kes: amount,
    method: "cash",
    paid_on: kenyaToday(),
  });
  expect(result.status, JSON.stringify(result.json)).toBe(201);
}

function owingRow(page: Page, name: string): Locator {
  return page.getByRole("table", { name: "Students owing fees" }).getByRole("row", { name: new RegExp(`^${name}'s`) });
}

async function openList(page: Page, query = "") {
  await page.goto(`/fees/arrears${query}`);
  await expect(page.getByRole("heading", { level: 1, name: "Students owing" })).toBeVisible();
  await expect(page.getByText("Loading...")).toHaveCount(0);
}

test("a finance officer sets, moves and removes a grade's pay-by date, shown on its bills", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const f = await feeClass(page);
  const bills = await issued(page, f);
  await logOut(page);
  await logInAs(page, FINANCE_EMAIL);
  const calendar = f.yearName.slice(-4);

  await page.goto(f.gradePage);
  const payBy = page.getByRole("region", { name: "Pay-by date" });
  await expect(payBy).toContainText("No pay-by date set.");
  // Term 1 runs from 6 January to 3 April: from 90 days before it starts.
  await expect(payBy).toContainText(
    `Any day from ${shown(`${Number(calendar) - 1}-10-08`)} to ${shown(`${calendar}-04-03`)}`,
  );
  const field = payBy.getByLabel("Pay by");
  await field.fill(`${calendar}-04-04`);
  await payBy.getByRole("button", { name: "Save pay-by date" }).click();
  await expect(payBy.getByRole("alert")).toHaveText(
    `Choose a pay-by date from ${shown(`${Number(calendar) - 1}-10-08`)} to ${shown(`${calendar}-04-03`)} (the term's last day).`,
  );

  await field.fill(`${calendar}-01-31`);
  await payBy.getByRole("button", { name: "Save pay-by date" }).click();
  await expect(page.getByRole("status")).toHaveText("Pay-by date saved.");
  await expect(payBy).toContainText(`Bills say "Pay by ${shown(`${calendar}-01-31`)}".`);
  await page.reload();
  await expect(page.getByRole("region", { name: "Pay-by date" }).getByLabel("Pay by")).toHaveValue(`${calendar}-01-31`);

  // The term overview, the bill and the printed bill say it too; the date
  // is still to come, so nothing is overdue.
  await page.goto(`/fees?year=${f.yearId}&term=1`);
  await expect(
    page.getByRole("row", { name: /^Grade 7 fees/ }).getByText(`Pay by ${shown(`${calendar}-01-31`)}`, { exact: true }),
  ).toBeVisible();
  await page.goto(`/fees/bills/${bills.Amani}`);
  await expect(page.getByText(`Pay by ${shown(`${calendar}-01-31`)}`, { exact: true })).toBeVisible();
  await expect(page.getByText("Overdue", { exact: true })).toHaveCount(0);
  await page.goto(`/fees/bills/${bills.Amani}/print`);
  const printed = page.getByRole("article", { name: `Bill for Amani ${f.id}` });
  await expect(printed.getByRole("definition").filter({ hasText: shown(`${calendar}-01-31`) })).toBeVisible();

  await page.goto(f.gradePage);
  await page.getByRole("button", { name: "Remove pay-by date" }).click();
  await expect(page.getByRole("status")).toHaveText("Pay-by date removed.");
  await expect(page.getByRole("region", { name: "Pay-by date" })).toContainText("No pay-by date set.");
  await page.goto(`/fees/bills/${bills.Amani}`);
  await expect(page.getByText(/^Pay by /)).toHaveCount(0);
});

test("a bill still owing after its pay-by date is marked overdue", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const c = await pastClass(page);
  await pay(page, c.bills.Baraka, 17_000);

  await page.goto(`/fees/bills/${c.bills.Amani}`);
  await expect(page.getByText(`Pay by ${shown(c.dueOn)}Overdue`)).toBeVisible();
  await page.goto(`/fees/bills/${c.bills.Baraka}`);
  await expect(page.getByText(`Pay by ${shown(c.dueOn)}`, { exact: true })).toBeVisible();
  await expect(page.getByText("Overdue", { exact: true })).toHaveCount(0);
});

test("Students owing lists a class's students with what they owe, what is overdue and whom to call", async ({
  page,
}) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const c = await pastClass(page);
  await logOut(page);
  await logInAs(page, FINANCE_EMAIL);
  await pay(page, c.bills.Amani, 5_000);

  await page.goto("/fees");
  await page.getByRole("link", { name: "Students owing" }).click();
  await expect(page).toHaveURL("/fees/arrears");
  await expect(page.getByText("Loading...")).toHaveCount(0);
  const filters = page.getByRole("form", { name: "Filter the list" });
  await filters.getByLabel("Grade").selectOption({ label: "Grade 1" });
  await filters.getByLabel("Class").selectOption({ label: c.className });
  await filters.getByRole("button", { name: "Show" }).click();
  await expect(page).toHaveURL(`/fees/arrears?grade=grade_1&class=${c.classId}`);
  await expect(page.getByText("Loading...")).toHaveCount(0);

  const table = page.getByRole("table", { name: "Students owing fees" });
  await expect(table.getByRole("rowgroup").nth(1).getByRole("row")).toHaveCount(2);
  const amani = owingRow(page, `Amani ${c.id}`);
  const cells = amani.getByRole("cell");
  await expect(cells).toHaveText([
    c.className,
    "KES 12,000",
    "KES 12,000",
    `Term 1, Past ${c.calendar}`,
    `${shown(kenyaToday())}: KES 5,000 (Cash)`,
    `Wanjiru ${c.id} (mother)0${c.phone.slice(4, 7)} ${c.phone.slice(7, 10)} ${c.phone.slice(10)}`,
  ]);
  const call = amani.getByRole("link", {
    name: `Call Wanjiru ${c.id} on 0${c.phone.slice(4, 7)} ${c.phone.slice(7, 10)} ${c.phone.slice(10)}`,
  });
  await expect(call).toHaveAttribute("href", `tel:${c.phone}`);
  await expect(owingRow(page, `Baraka ${c.id}`).getByRole("cell").last()).toHaveText("No guardian recorded");
  // Largest first: Baraka owes 17,000, Amani 12,000.
  await expect(table.getByRole("rowheader").first()).toContainText(`Baraka ${c.id}`);
  await expect(page.getByRole("status")).toHaveText("2 students owe KES 29,000, of which KES 29,000 is overdue.");
  await expect(table.getByRole("rowgroup").last()).toContainText(
    "All 2 studentsOwed now: KES 29,000Overdue: KES 29,000",
  );

  // At least 15,000: only Baraka. Then the name opens the fee statement.
  await filters.getByLabel("Owing at least (KES)").fill("15,000");
  await filters.getByRole("button", { name: "Show" }).click();
  await expect(page).toHaveURL(`/fees/arrears?grade=grade_1&class=${c.classId}&min=15000`);
  // (Wait for the new list before checking who is missing from it.)
  await expect(page.getByRole("status")).toHaveText("1 student owes KES 17,000, of which KES 17,000 is overdue.");
  await expect(owingRow(page, `Amani ${c.id}`)).toHaveCount(0);
  await owingRow(page, `Baraka ${c.id}`)
    .getByRole("link", { name: `Baraka ${c.id}'s fee statement` })
    .click();
  await expect(page).toHaveURL(`/fees/students/${c.students.Baraka}/statement`);
});

test("the list can show overdue only, be ordered by class, and has a way back to everyone", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const past = await pastClass(page);
  // Past Amani owes 12,000 and future Amani 17,000: largest first puts the
  // future class first, by class the past one (Grade 1 before Grade 7).
  await pay(page, past.bills.Amani, 5_000);
  const future = await feeClass(page);
  await issued(page, future);
  const futureClass = `Grade 7 ${future.id}`;

  await openList(page);
  const before = await page
    .getByRole("table", { name: "Students owing fees" })
    .getByRole("rowheader")
    .allTextContents();
  expect(before.findIndex((h) => h.includes(`Amani ${future.id}`))).toBeLessThan(
    before.findIndex((h) => h.includes(`Amani ${past.id}`)),
  );

  await openList(page, "?overdue=1");
  await expect(page.getByRole("form", { name: "Filter the list" }).getByLabel("Overdue only")).toBeChecked();
  await expect(owingRow(page, `Amani ${past.id}`)).toBeVisible();
  // Future pay-by dates (none set here): owed but not overdue, so not listed.
  await expect(owingRow(page, `Amani ${future.id}`)).toHaveCount(0);

  await page.getByRole("link", { name: "Clear filters" }).click();
  await expect(page).toHaveURL("/fees/arrears");
  await expect(owingRow(page, `Amani ${future.id}`)).toContainText("None");

  await page.getByLabel("Order").selectOption({ label: "By class" });
  await expect(page).toHaveURL("/fees/arrears?order=class");
  const headers = await page
    .getByRole("table", { name: "Students owing fees" })
    .getByRole("rowheader")
    .allTextContents();
  const past1 = headers.findIndex((h) => h.includes(`Amani ${past.id}`));
  const future1 = headers.findIndex((h) => h.includes(`Amani ${future.id}`));
  // Grade 1 comes before Grade 7.
  expect(past1).toBeGreaterThanOrEqual(0);
  expect(future1).toBeGreaterThan(past1);
  await expect(owingRow(page, `Amani ${future.id}`).getByRole("cell").first()).toHaveText(futureClass);

  await openList(page, "?min=abc&grade=nonsense");
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Clear the filters to see everyone owing.");
  await page.getByRole("link", { name: "Clear filters" }).click();
  await expect(page).toHaveURL("/fees/arrears");
});

test("the printed list is landscape, says what it shows and that it is confidential", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const c = await pastClass(page);
  await openList(page, `?class=${c.classId}&overdue=1`);

  await page.emulateMedia({ media: "print" });
  await expect(page.getByRole("form", { name: "Filter the list" })).toBeHidden();
  await expect(page.getByRole("button", { name: "Print list" })).toBeHidden();
  await expect(page.getByText(`Showing ${c.className}, overdue only.`)).toBeVisible();
  await expect(page.getByText(/^Students owing fees, /)).toBeVisible();
  await expect(page.getByText("Confidential: guardian contacts for fee follow-up only.")).toHaveCount(2);
  // On paper the table keeps its column headings.
  await expect(page.getByRole("columnheader", { name: "Contact" })).toBeVisible();

  // A4 landscape: 842 by 595 points.
  const pdf = (await page.pdf({ preferCSSPageSize: true })).toString("latin1");
  expect(pdf).toMatch(/\/MediaBox \[0 0 84[12]\.\d+ 59[45]\.\d+\]/);
  // Two students fit on one page, totals included.
  expect(pdf.match(/\/Type \/Page\b(?!s)/g)).toHaveLength(1);
  await page.emulateMedia({ media: "screen" });
});

test("a teacher has no Students owing page", async ({ page }) => {
  await logInAs(page, ATTENDANCE_TEACHER_EMAIL);
  await page.goto("/fees/arrears");
  await expect(page.getByText("You do not have access to this page in E2E School C.")).toBeVisible();
  const response = await call(page, "GET", "/school/fees/arrears");
  expect(response.status).toBe(403);
});

// The table is shown as blocks: headings hidden, rows as blocks, and each
// cell's column name drawn before it. Returns the labels drawn in the first
// row.
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

async function scrollsSideways(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll("main *"))
      .filter((el) => ["auto", "scroll"].includes(getComputedStyle(el).overflowX))
      .filter((el) => el.scrollWidth > el.clientWidth + 1)
      .map((el) => `${el.tagName.toLowerCase()} is ${el.scrollWidth}px wide in ${el.clientWidth}px`),
  );
}

test("the list and the pay-by date fit a phone screen", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const f = await feeClass(page, { widest: true });
  await issued(page, f);
  await page.setViewportSize(PHONE);
  await openList(page, `?class=${f.classId}`);
  await page.addStyleTag({ content: WIDE_FONT });
  expect(await stackedLabels(page.getByRole("table", { name: "Students owing fees" }))).toEqual([
    "none",
    "Class: ",
    "Owed now: ",
    "Overdue: ",
    "Oldest unpaid: ",
    "Last payment: ",
    "Contact: ",
  ]);
  expect(await offScreen(page)).toEqual([]);
  expect(await scrollsSideways(page)).toEqual([]);

  await page.goto(f.gradePage);
  await expect(page.getByRole("region", { name: "Pay-by date" })).toBeVisible();
  await page.addStyleTag({ content: WIDE_FONT });
  expect(await offScreen(page)).toEqual([]);
});

for (const scheme of ["light", "dark"] as const) {
  test(`pay-by dates and Students owing pass the accessibility checks (${scheme})`, async ({ page }) => {
    test.setTimeout(90_000);
    await page.emulateMedia({ colorScheme: scheme });
    await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
    const c = await pastClass(page);
    const found: string[] = [];
    for (const [what, path, ready] of [
      ["grade page", `/fees/${c.yearId}/1/grade_1`, "Pay-by date"],
      ["overdue bill", `/fees/bills/${c.bills.Amani}`, "Overdue"],
      ["students owing", `/fees/arrears?class=${c.classId}`, `All 2 students`],
    ]) {
      await page.goto(path);
      await expect(page.getByText(ready, { exact: false }).first()).toBeVisible();
      found.push(...(await problems(page)).map((p) => `${what}: ${p}`));
      if (what === "grade page") {
        // Its bills table still scrolls sideways on a phone (from E1, an
        // open item); its pay-by date is checked on a phone below.
        continue;
      }
      await page.setViewportSize(PHONE);
      found.push(...(await problems(page)).map((p) => `${what} on a phone: ${p}`));
      await page.setViewportSize({ width: 1280, height: 720 });
    }
    expect(found).toEqual([]);
  });
}
