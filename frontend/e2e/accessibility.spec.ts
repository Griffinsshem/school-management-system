import { expect, test, type Page } from "@playwright/test";

import { problems } from "./axe";
import { ATTENDANCE_ADMIN_EMAIL, ATTENDANCE_TEACHER_EMAIL, SCHOOL_C, logIn } from "./helpers";

// Automatic accessibility checks (D8): every main page, as a school
// administrator and as a class teacher, in light and dark mode, plus error
// messages, notices and open forms, checked against WCAG 2.1 level A and AA
// with axe-core (see axe.ts). The fee pages are checked in fees.spec.ts.
// In E2E School C (see marks.spec.ts). All names are made up.

type Json = Record<string, unknown>;

async function call(page: Page, method: string, path: string, body?: object) {
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

function kenyaDate(days: number): string {
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(new Date());
  const date = new Date(`${today}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

let counter = 0;
function unique(): string {
  counter += 1;
  return `${Date.now().toString(36).slice(-5).toUpperCase()}${counter}`;
}

async function logInAs(page: Page, email: string) {
  await page.goto("/login");
  await logIn(page, email);
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL_C })).toBeVisible();
}

// School C's year around today, shared with the other School C tests.
async function currentYear(page: Page): Promise<string> {
  const { json } = await call(page, "GET", "/school/academic-years");
  const existing = (json.academic_years as { id: string; name: string }[]).find((y) => y.name === "E2E now");
  if (existing) {
    return existing.id;
  }
  const created = await call(page, "POST", "/school/academic-years", {
    name: "E2E now",
    starts_on: kenyaDate(-60),
    ends_on: kenyaDate(200),
    terms: [{ number: 1, starts_on: kenyaDate(-60), ends_on: kenyaDate(100) }],
  });
  expect(created.status).toBe(201);
  return (created.json.academic_year as { id: string }).id;
}

// A Grade 6 class with Amani and Baraka, taking Mathematics with one
// assessment (out of 10, no marks yet), set up by the administrator.
async function smallClass(page: Page) {
  const id = unique();
  const made = await call(page, "POST", "/school/classes", {
    academic_year_id: await currentYear(page),
    grade: "grade_6",
    stream: id,
  });
  expect(made.status).toBe(201);
  const classId = (made.json.class as { id: string }).id;
  const students: Record<string, string> = {};
  for (const [n, first] of ["Amani", "Baraka"].entries()) {
    const student = await call(page, "POST", "/school/students", {
      admission_number: `UC${id}-${n + 1}`,
      full_name: `${first} ${id}`,
    });
    expect(student.status).toBe(201);
    students[first] = (student.json.student as { id: string }).id;
  }
  expect((await call(page, "POST", `/school/classes/${classId}/students`, { student_ids: Object.values(students) })).status).toBe(201);
  const subject = await call(page, "POST", "/school/subjects", { name: `Mathematics ${id}` });
  expect(subject.status).toBe(201);
  const subjectId = (subject.json.subject as { id: string }).id;
  expect((await call(page, "POST", `/school/classes/${classId}/subjects`, { subject_id: subjectId })).status).toBe(201);
  const exam = await call(page, "POST", `/school/classes/${classId}/subjects/${subjectId}/assessments`, {
    term: 1,
    name: "Quiz",
    max_score: 10,
    held_on: kenyaDate(0),
  });
  expect(exam.status).toBe(201);
  return { id, classId, students, assessmentId: (exam.json.assessment as { id: string }).id };
}

// A class taught by the teacher, with a mark, ready for every page.
async function schoolData(page: Page) {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const c = await smallClass(page);
  const { json } = await call(page, "GET", "/school/members");
  const teacher = (json.members as { id: string; role: string; user: { email: string } }[]).find(
    (m) => m.user.email === ATTENDANCE_TEACHER_EMAIL && m.role === "teacher",
  );
  expect((await call(page, "POST", `/school/classes/${c.classId}/teachers`, { membership_id: teacher?.id })).status).toBe(201);
  const marks = { marks: [{ student_id: c.students.Amani, score: 7 }] };
  expect((await call(page, "PUT", `/school/assessments/${c.assessmentId}/marks`, marks)).status).toBe(200);
  return c;
}

function pagesOf(c: Awaited<ReturnType<typeof smallClass>>): string[] {
  const cls = `/classes/${c.classId}`;
  return [
    "/",
    "/school-year",
    "/classes",
    cls,
    `${cls}/attendance?date=${kenyaDate(0)}`,
    "/attendance",
    `${cls}/attendance/summary`,
    "/subjects",
    "/students",
    `/students/${c.students.Amani}`,
    "/people",
    "/grading",
    `${cls}/marks?term=1`,
    `/assessments/${c.assessmentId}`,
    `${cls}/results?term=1`,
    `${cls}/report-cards?term=1`,
    `${cls}/report-cards/${c.students.Amani}?term=1`,
    `${cls}/report-cards/print?term=1`,
  ];
}

async function checkPages(page: Page, paths: string[]) {
  const found: string[] = [];
  for (const path of paths) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
    await expect(page.getByText("Loading...")).toHaveCount(0);
    found.push(...(await problems(page)).map((p) => `${path}: ${p}`));
  }
  expect(found).toEqual([]);
}

test("logged-out pages pass", async ({ page }) => {
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto("/login");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(await problems(page)).toEqual([]);
    await page.goto("/invitations/accept#token=made-up-token");
    await expect(page.getByRole("heading", { name: "This link is not valid" })).toBeVisible();
    expect(await problems(page)).toEqual([]);
  }
});

for (const scheme of ["light", "dark"] as const) {
  test(`every main page passes for an administrator and a teacher (${scheme})`, async ({ page }) => {
    test.setTimeout(120_000);
    await page.emulateMedia({ colorScheme: scheme });
    const c = await schoolData(page);
    await checkPages(page, pagesOf(c));

    await page.getByRole("button", { name: "Log out" }).click();
    await expect(page).toHaveURL("/login");
    await logInAs(page, ATTENDANCE_TEACHER_EMAIL);
    await checkPages(page, pagesOf(c));
  });

  test(`messages and open forms pass (${scheme})`, async ({ page }) => {
    test.setTimeout(90_000);
    await page.emulateMedia({ colorScheme: scheme });
    const c = await schoolData(page);
    const main = page.getByRole("main");
    const found: string[] = [];
    const check = async (state: string) => found.push(...(await problems(page)).map((p) => `${state}: ${p}`));

    await page.goto(`/classes/${c.classId}/report-cards?term=1`);
    const box = page.getByLabel(`Comment for Amani ${c.id}`);
    const save = page.getByRole("button", { name: `Save comment for Amani ${c.id}` });
    await box.fill("   ");
    await save.click();
    await expect(main.getByRole("alert")).toBeVisible();
    await check("error message");
    await box.fill("Fine.");
    await save.click();
    await expect(main.getByRole("status")).toBeVisible();
    await check("saved notice");

    await page.goto("/students");
    await page.getByRole("button", { name: "Add a student" }).click();
    await check("add-student form");
    await page.goto("/classes");
    await page.getByRole("button", { name: "Add a class" }).click();
    await check("add-class form");
    await page.goto(`/assessments/${c.assessmentId}`);
    await page.getByRole("button", { name: "Edit details" }).click();
    await check("assessment details form");
    await page.goto("/grading");
    await page.getByRole("button", { name: "Change boundaries" }).click();
    await check("boundaries form");
    expect(found).toEqual([]);
  });
}
