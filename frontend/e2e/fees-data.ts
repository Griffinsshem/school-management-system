import { expect, type Page } from "@playwright/test";

import { SCHOOL_C, logIn } from "./helpers";

// Shared by the fee tests (E1, fees.spec.ts), the payment tests (E2,
// payments.spec.ts) and the statement tests (E3, statements.spec.ts): API
// calls from the logged-in page, and a school year of the test's own with a
// billed Grade 7 class. All names are made up.

export type Json = Record<string, unknown>;

export async function call(page: Page, method: string, path: string, body?: object) {
  return page.evaluate(
    async ([method, path, body]) => {
      const response = await fetch(`/api/v1${path}`, {
        method,
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
      return { status: response.status, json: (await response.json()) as Json };
    },
    [method, path, body] as const,
  );
}

let counter = 0;
export function unique(): string {
  counter += 1;
  return `${Date.now().toString(36).slice(-5).toUpperCase()}${counter}`;
}

export async function logInAs(page: Page, email: string) {
  await page.goto("/login");
  await logIn(page, email);
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL_C })).toBeVisible();
}

export async function logOut(page: Page) {
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL("/login");
}

// A school year of the test's own (the first calendar year from 2030 not
// used yet) with Term 1 (and Term 2 when `terms` is 2), a Grade 7 class with
// Amani and Baraka, and Amani's mother as her guardian. Set up by the
// administrator. `widest` uses the longest stream (20) and admission
// numbers (30) the school can enter.
export async function feeClass(page: Page, { widest = false, terms = 1 } = {}) {
  const id = unique();
  const { json } = await call(page, "GET", "/school/academic-years");
  const used = new Set((json.academic_years as { starts_on: string }[]).map((y) => Number(y.starts_on.slice(0, 4))));
  let calendar = 2030;
  while (used.has(calendar)) {
    calendar += 1;
  }
  const year = await call(page, "POST", "/school/academic-years", {
    name: `Fees ${calendar}`,
    starts_on: `${calendar}-01-06`,
    ends_on: `${calendar}-11-20`,
    terms: [
      { number: 1, starts_on: `${calendar}-01-06`, ends_on: `${calendar}-04-03` },
      { number: 2, starts_on: `${calendar}-05-04`, ends_on: `${calendar}-08-01` },
    ].slice(0, terms),
  });
  expect(year.status).toBe(201);
  const yearId = (year.json.academic_year as { id: string }).id;
  const made = await call(page, "POST", "/school/classes", {
    academic_year_id: yearId,
    grade: "grade_7",
    stream: widest ? id.padEnd(20, "W") : id,
  });
  expect(made.status).toBe(201);
  const classId = (made.json.class as { id: string }).id;
  const students: Record<string, string> = {};
  for (const [n, first] of ["Amani", "Baraka"].entries()) {
    const student = await call(page, "POST", "/school/students", {
      admission_number: widest ? `FE${id}N${n + 1}`.padEnd(30, "0") : `FE${id}-${n + 1}`,
      full_name: `${first} ${id}`,
    });
    expect(student.status).toBe(201);
    students[first] = (student.json.student as { id: string }).id;
  }
  const enrol = await call(page, "POST", `/school/classes/${classId}/students`, { student_ids: Object.values(students) });
  expect(enrol.status).toBe(201);
  const phone = `+2547${String(Date.now() + counter).slice(-8)}`;
  const guardian = await call(page, "POST", `/school/students/${students.Amani}/guardians`, {
    full_name: `Wanjiru ${id}`,
    phone,
    relationship: "mother",
  });
  expect(guardian.status).toBe(201);
  const grade = `/school/fees/years/${yearId}/terms/1/grades/grade_7`;
  const yearName = `Fees ${calendar}`;
  const termGrade = (term: number) => `/school/fees/years/${yearId}/terms/${term}/grades/grade_7`;
  return { id, yearId, yearName, classId, students, phone, grade, termGrade, gradePage: `/fees/${yearId}/1/grade_7` };
}

export type FeeClass = Awaited<ReturnType<typeof feeClass>>;

// Tuition and Activity for everyone, Boarding optional; bills issued for
// the term (Term 1 unless said).
export async function issued(page: Page, f: FeeClass, term = 1) {
  const items = [
    { name: "Tuition", amount_kes: 15_000 },
    { name: "Activity", amount_kes: 2_000 },
    { name: "Boarding", amount_kes: 30_000, is_optional: true },
  ];
  expect((await call(page, "PUT", f.termGrade(term), { items })).status).toBe(200);
  const result = await call(page, "POST", `${f.termGrade(term)}/issue`);
  expect(result.status).toBe(200);
  const bills = result.json.bills as { id: string; student: { id: string } }[];
  return Object.fromEntries(bills.map((b) => [b.student.id === f.students.Amani ? "Amani" : "Baraka", b.id]));
}

export function menu(page: Page) {
  return page.getByRole("navigation", { name: "Main" });
}

// Elements running past the right edge of the screen, except inside a box
// that scrolls sideways on its own (as in report-cards.spec.ts).
export async function offScreen(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    const scrolls = (el: Element | null): boolean => {
      for (let e = el; e && e !== document.body; e = e.parentElement) {
        if (["auto", "scroll"].includes(getComputedStyle(e).overflowX)) {
          return true;
        }
      }
      return false;
    };
    const outside: string[] = [];
    if (document.documentElement.scrollWidth > width) {
      outside.push(`page is ${document.documentElement.scrollWidth}px wide`);
    }
    for (const el of Array.from(document.querySelectorAll("main *"))) {
      const box = el.getBoundingClientRect();
      if (box.width > 0 && box.right > width + 0.5 && !scrolls(el.parentElement)) {
        outside.push(`${el.tagName.toLowerCase()} "${(el.textContent ?? "").trim().slice(0, 30)}" ends at ${Math.round(box.right)}px`);
      }
    }
    return outside;
  });
}
