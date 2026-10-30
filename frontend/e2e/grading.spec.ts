import { expect, test, type Page } from "@playwright/test";

import { ATTENDANCE_ADMIN_EMAIL, ATTENDANCE_TEACHER_EMAIL, SCHOOL_C, errorMessage, logIn } from "./helpers";

// Grading scales and grades (D5), in E2E School C (see marks.spec.ts). KCSE
// boundaries belong to the whole school, so a test that changes them puts
// the defaults back afterwards, even when it fails.

type Json = Record<string, unknown>;

const DEFAULT_KCSE = {
  A: 80, "A-": 75, "B+": 70, B: 65, "B-": 60, "C+": 55,
  C: 50, "C-": 45, "D+": 40, D: 35, "D-": 30, E: 0,
}; // prettier-ignore

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

async function logOut(page: Page) {
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL("/login");
}

function notice(page: Page) {
  return page.getByRole("main").getByRole("status");
}

// School C's year around today, shared with the attendance and marks tests.
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

// A class of the given grade level with three students taking a new subject,
// set up by School C's administrator (logged in); the teacher is its subject
// teacher or its class teacher.
async function classWithSubject(page: Page, grade: string, teacherIs: "subject" | "class") {
  const id = unique();
  const yearId = await currentYear(page);
  const made = await call(page, "POST", "/school/classes", { academic_year_id: yearId, grade, stream: id });
  expect(made.status).toBe(201);
  const classId = (made.json.class as { id: string }).id;
  const students: Record<string, string> = {};
  for (const [n, first] of ["Amani", "Baraka", "Chausiku"].entries()) {
    const student = await call(page, "POST", "/school/students", {
      admission_number: `G${id}-${n + 1}`,
      full_name: `${first} ${id}`,
    });
    expect(student.status).toBe(201);
    students[first] = (student.json.student as { id: string }).id;
  }
  const enrolled = await call(page, "POST", `/school/classes/${classId}/students`, {
    student_ids: Object.values(students),
  });
  expect(enrolled.status).toBe(201);
  const subject = await call(page, "POST", "/school/subjects", { name: `Physics ${id}` });
  expect(subject.status).toBe(201);
  const subjectId = (subject.json.subject as { id: string }).id;
  expect((await call(page, "POST", `/school/classes/${classId}/subjects`, { subject_id: subjectId })).status).toBe(201);
  const { json } = await call(page, "GET", "/school/members");
  const teacher = (json.members as { id: string; role: string; user: { email: string } }[]).find(
    (m) => m.user.email === ATTENDANCE_TEACHER_EMAIL && m.role === "teacher",
  );
  const assign =
    teacherIs === "subject"
      ? `/school/classes/${classId}/subjects/${subjectId}/teachers`
      : `/school/classes/${classId}/teachers`;
  expect((await call(page, "POST", assign, { membership_id: teacher?.id })).status).toBe(201);
  return { id, classId, subjectId, subject: `Physics ${id}`, students };
}

async function addAssessment(page: Page, classId: string, subjectId: string, name: string, max: number) {
  const created = await call(page, "POST", `/school/classes/${classId}/subjects/${subjectId}/assessments`, {
    term: 1,
    name,
    max_score: max,
    held_on: kenyaDate(0),
  });
  expect(created.status).toBe(201);
  return (created.json.assessment as { id: string }).id;
}

function scoreBox(page: Page, first: string, id: string) {
  return page.getByLabel(new RegExp(`^Score for ${first} ${id}`));
}

function liveGrade(page: Page, first: string, id: string) {
  return page.getByRole("listitem").filter({ hasText: `${first} ${id}` }).getByTestId("live-grade");
}

async function restoreDefaults(page: Page) {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const saved = await call(page, "PUT", "/school/grading/kcse", { boundaries: DEFAULT_KCSE });
  expect(saved.status).toBe(200);
}

test("a logged-out visitor is sent to the login page", async ({ page }) => {
  await page.goto("/grading");
  await expect(page).toHaveURL("/login?next=%2Fgrading");
});

test("a Form mark shows its KCSE grade as it is typed, and follows the school's boundaries", async ({ page }) => {
  try {
    await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
    const c = await classWithSubject(page, "form_4", "subject");
    const cat = await addAssessment(page, c.classId, c.subjectId, "CAT 1", 10);
    await logOut(page);

    // The subject teacher sees the grade while typing, from the school's scale.
    await logInAs(page, ATTENDANCE_TEACHER_EMAIL);
    await page.goto(`/assessments/${cat}`);
    await expect(page.getByRole("link", { name: "KCSE scale" })).toBeVisible();
    await scoreBox(page, "Amani", c.id).fill("7.9");
    await expect(liveGrade(page, "Amani", c.id)).toHaveText("79% A-");
    await scoreBox(page, "Amani", c.id).fill("8");
    await expect(liveGrade(page, "Amani", c.id)).toHaveText("80% A");
    await page.getByRole("button", { name: "Save marks" }).click();
    await expect(notice(page)).toHaveText("Marks saved.");
    await logOut(page);

    // An administrator raises A to 85: refused first while it is not above A-.
    await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
    await page.goto("/grading");
    await expect(page.getByText(/These are the default boundaries/)).toBeVisible();
    await page.getByRole("button", { name: "Change boundaries" }).click();
    await page.getByLabel("Lowest percentage for A", { exact: true }).fill("70");
    await page.getByRole("button", { name: "Save boundaries" }).click();
    await expect(errorMessage(page)).toContainText("A must start higher than A- (70 is not above 75).");
    await page.getByLabel("Lowest percentage for A", { exact: true }).fill("85");
    await page.getByRole("button", { name: "Save boundaries" }).click();
    await expect(notice(page)).toContainText("Boundaries saved.");
    await expect(page.getByText("This school has set its own boundaries.")).toBeVisible();

    // The same 8 out of 10 is now an A-.
    await page.goto(`/assessments/${cat}`);
    await expect(liveGrade(page, "Amani", c.id)).toHaveText("80% A-");

    // Back to the defaults, from the page.
    await page.goto("/grading");
    await page.getByRole("button", { name: "Change boundaries" }).click();
    await page.getByRole("button", { name: "Fill in the defaults" }).click();
    await expect(page.getByLabel("Lowest percentage for A", { exact: true })).toHaveValue("80");
    await page.getByRole("button", { name: "Save boundaries" }).click();
    await expect(page.getByText(/These are the default boundaries/)).toBeVisible();
    await page.goto(`/assessments/${cat}`);
    await expect(liveGrade(page, "Amani", c.id)).toHaveText("80% A");
  } finally {
    await restoreDefaults(page);
  }
});

test("the overview grades each mark and adds up each subject's term", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const c = await classWithSubject(page, "grade_5", "class");
  const cat = await addAssessment(page, c.classId, c.subjectId, "CAT", 10);
  const exam = await addAssessment(page, c.classId, c.subjectId, "Exam", 20);
  for (const [assessment, score] of [
    [cat, 8],
    [exam, 15],
  ] as const) {
    const saved = await call(page, "PUT", `/school/assessments/${assessment}/marks`, {
      marks: [
        { student_id: c.students.Amani, score },
        { student_id: c.students.Baraka, did_not_sit: true },
      ],
    });
    expect(saved.status).toBe(200);
  }
  await logOut(page);

  // The class teacher reads it: 8/10 is 80% and 15/20 is 75% (both EE2), and
  // the term adds up to 23/30, 77% (EE2). Baraka sat nothing.
  await logInAs(page, ATTENDANCE_TEACHER_EMAIL);
  await page.goto(`/classes/${c.classId}/marks`);
  await expect(page.getByRole("link", { name: "CBC (KJSEA) scale" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: `${c.subject}: Term 1 total` })).toBeVisible();
  const amani = page.getByRole("row", { name: new RegExp(`^Amani ${c.id}`) }).getByRole("cell");
  await expect(amani.nth(0)).toHaveText("8 (80%) EE2");
  await expect(amani.nth(1)).toHaveText("15 (75%) EE2");
  await expect(amani.nth(2)).toHaveText("23 / 30 (77%) EE2");
  const baraka = page.getByRole("row", { name: new RegExp(`^Baraka ${c.id}`) }).getByRole("cell");
  await expect(baraka.nth(2)).toHaveText("—");

  // A read-only sheet shows each grade with its points.
  await page.getByRole("link", { name: `${c.subject}: CAT` }).click();
  await expect(page.getByRole("heading", { level: 1, name: "CAT" })).toBeVisible();
  await expect(page.getByRole("row", { name: new RegExp(`Amani ${c.id}`) })).toContainText("EE2 (7)");
});

test("the grade shown while typing matches the server's at the rounding edge", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const c = await classWithSubject(page, "grade_5", "subject");
  const exam = await addAssessment(page, c.classId, c.subjectId, "Exam", 200);
  await logOut(page);

  await logInAs(page, ATTENDANCE_TEACHER_EMAIL);
  await page.goto(`/assessments/${exam}`);
  // 179/200 is 89.5%, shown as 90%: EE1. 178.9/200 is 89.45%: 89%, EE2.
  await scoreBox(page, "Amani", c.id).fill("179");
  await scoreBox(page, "Baraka", c.id).fill("178.9");
  await expect(liveGrade(page, "Amani", c.id)).toHaveText("90% EE1");
  await expect(liveGrade(page, "Baraka", c.id)).toHaveText("89% EE2");
  await page.getByRole("button", { name: "Save marks" }).click();
  await expect(notice(page)).toHaveText("Marks saved.");

  const { json } = await call(page, "GET", `/school/assessments/${exam}/marks`);
  const results = Object.fromEntries(
    (json.students as { full_name: string; result: { percent: number; grade: string } | null }[]).map((s) => [
      s.full_name.split(" ")[0],
      s.result && `${s.result.percent}% ${s.result.grade}`,
    ]),
  );
  expect(results).toEqual({ Amani: "90% EE1", Baraka: "89% EE2", Chausiku: null });
});

test("teachers read the grading scales but cannot change them", async ({ page }) => {
  await logInAs(page, ATTENDANCE_TEACHER_EMAIL);
  await page.goto("/grading");
  await expect(page.getByRole("heading", { level: 1, name: "Grading" })).toBeVisible();
  await expect(page.getByRole("table", { name: "KCSE grade boundaries" })).toContainText("80 to 100");
  await expect(page.getByRole("table", { name: "CBC performance levels" })).toContainText("EE1");
  await expect(page.getByRole("button", { name: "Change boundaries" })).toHaveCount(0);
});

test("the grading page fits a phone screen without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  await page.goto("/grading");
  await page.getByRole("button", { name: "Change boundaries" }).click();
  await expect(page.getByLabel("Lowest percentage for E")).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBe(0);
});
