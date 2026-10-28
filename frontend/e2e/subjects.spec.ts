import { expect, test, type Page } from "@playwright/test";

import {
  ATTENDANCE_ADMIN_EMAIL,
  ATTENDANCE_TEACHER_EMAIL,
  PRINCIPAL_EMAIL,
  SCHOOL_A,
  SCHOOL_C,
  TEACHER_EMAIL,
  errorMessage,
  logIn,
  logInToSchoolA,
} from "./helpers";

// Subjects, the subjects each class takes and their teachers (D3). Each test
// makes its own subjects and classes with names of its own, so tests do not
// depend on each other.

type Json = Record<string, unknown>;

const PAST_YEAR = { name: "E2E 2025", starts_on: "2025-01-06", ends_on: "2025-11-28" };

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

let counter = 0;
function unique(): string {
  counter += 1;
  return `${Date.now().toString(36).slice(-5).toUpperCase()}${counter}`;
}

function kenyaDate(days: number): string {
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(new Date());
  const date = new Date(`${today}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

// A school year of the logged-in administrator's school, created the first time.
async function yearNamed(page: Page, year: { name: string } & Json) {
  const { json } = await call(page, "GET", "/school/academic-years");
  const existing = (json.academic_years as { id: string; name: string }[]).find((y) => y.name === year.name);
  if (existing) {
    return existing.id;
  }
  const created = await call(page, "POST", "/school/academic-years", year);
  expect(created.status).toBe(201);
  return (created.json.academic_year as { id: string }).id;
}

async function newClass(page: Page, yearId: string, stream: string): Promise<string> {
  const made = await call(page, "POST", "/school/classes", { academic_year_id: yearId, grade: "grade_4", stream });
  expect(made.status).toBe(201);
  return (made.json.class as { id: string }).id;
}

async function newSubject(page: Page, name: string, code?: string): Promise<string> {
  const made = await call(page, "POST", "/school/subjects", { name, code });
  expect(made.status).toBe(201);
  return (made.json.subject as { id: string }).id;
}

async function teacherId(page: Page, email: string): Promise<string> {
  const { json } = await call(page, "GET", "/school/members");
  const member = (json.members as { id: string; role: string; user: { email: string } }[]).find(
    (m) => m.user.email === email && m.role === "teacher",
  );
  expect(member).toBeDefined();
  return member!.id;
}

function notice(page: Page) {
  return page.getByRole("main").getByRole("status");
}

function subjectRow(page: Page, name: string) {
  return page.getByRole("table").getByRole("row", { name: new RegExp(`^${name}\\b`) });
}

function classSubject(page: Page, name: string) {
  return page.getByRole("listitem", { name, exact: true });
}

async function logOut(page: Page) {
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL("/login");
}

test("a logged-out visitor is sent to the login page", async ({ page }) => {
  await page.goto("/subjects");

  await expect(page).toHaveURL("/login?next=%2Fsubjects");
});

test("an administrator keeps the school's subject list", async ({ page }) => {
  await logInToSchoolA(page);
  const id = unique();
  await page.getByRole("link", { name: "Subjects" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Subjects" })).toBeVisible();

  await page.getByRole("button", { name: "Add a subject" }).click();
  await expect(page.getByRole("heading", { name: "Add a subject" })).toBeFocused();
  await page.getByRole("button", { name: "Add subject" }).click();
  await expect(errorMessage(page)).toHaveText("Enter the subject's name.");
  await page.getByLabel(/^Name/).fill(`  Biology   ${id} `);
  await page.getByLabel(/^Short code/).fill(`B${id}`);
  await page.getByRole("button", { name: "Add subject" }).click();
  await expect(notice(page)).toHaveText(`Added Biology ${id}.`);
  await expect(subjectRow(page, `Biology ${id}`)).toContainText(`B${id}`);
  await expect(subjectRow(page, `Biology ${id}`)).toContainText("Active");

  // The same name, in other letters, is refused.
  await page.getByRole("button", { name: "Add a subject" }).click();
  await page.getByLabel(/^Name/).fill(`BIOLOGY ${id}`);
  await page.getByRole("button", { name: "Add subject" }).click();
  await expect(errorMessage(page)).toHaveText(`This school already has BIOLOGY ${id}.`);
  await page.getByRole("button", { name: "Cancel" }).click();

  // Renamed, its code removed, then made inactive: never deleted.
  await page.getByRole("button", { name: `Edit Biology ${id}` }).click();
  await page.getByLabel(/^Name/).fill(`Biology Studies ${id}`);
  await page.getByLabel(/^Short code/).fill("");
  await page.getByLabel(/^Active/).uncheck();
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(notice(page)).toHaveText(`Saved Biology Studies ${id}.`);
  await expect(subjectRow(page, `Biology Studies ${id}`)).toContainText("None");
  await expect(subjectRow(page, `Biology Studies ${id}`)).toContainText("Inactive");
});

test("an administrator chooses a class's subjects and their teachers", async ({ page }) => {
  await logInToSchoolA(page);
  const id = unique();
  const yearId = await yearNamed(page, PAST_YEAR);
  const classId = await newClass(page, yearId, `S${id}`);
  await newSubject(page, `Chemistry ${id}`);
  const physics = await newSubject(page, `Physics ${id}`);
  expect((await call(page, "PATCH", `/school/subjects/${physics}`, { is_active: false })).status).toBe(200);
  const className = `Grade 4 S${id}`;

  await page.goto(`/classes/${classId}`);
  await expect(page.getByRole("heading", { level: 1, name: className })).toBeVisible();
  await expect(page.getByText(`${className} takes no subjects yet.`)).toBeVisible();
  // An inactive subject is not offered.
  const choices = page.getByLabel("Add a subject");
  await expect(choices.getByRole("option", { name: `Physics ${id}` })).toHaveCount(0);

  await choices.selectOption({ label: `Chemistry ${id}` });
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(notice(page)).toHaveText(`${className} now takes Chemistry ${id}.`);
  const chemistry = classSubject(page, `Chemistry ${id}`);
  await expect(chemistry).toContainText("No teacher yet.");

  await chemistry.getByLabel(`Add a teacher for Chemistry ${id}`).selectOption({ label: "E2E Teacher" });
  await chemistry.getByRole("button", { name: "Add", exact: true }).click();
  await expect(notice(page)).toHaveText(`E2E Teacher now teaches Chemistry ${id} in ${className}.`);
  await expect(chemistry).toContainText("E2E Teacher");

  await page.getByRole("button", { name: `Remove E2E Teacher from Chemistry ${id}` }).click();
  await expect(notice(page)).toHaveText(`E2E Teacher no longer teaches Chemistry ${id} in ${className}.`);
  await expect(chemistry).toContainText("No teacher yet.");

  await page.getByRole("button", { name: `Remove Chemistry ${id} from ${className}` }).click();
  await page.getByRole("button", { name: "Yes, remove" }).click();
  await expect(notice(page)).toHaveText(`${className} no longer takes Chemistry ${id}.`);
  await expect(page.getByText(`${className} takes no subjects yet.`)).toBeVisible();
});

test("a subject teacher sees the class and its names, but takes no register", async ({ page }) => {
  await page.goto("/login");
  await logIn(page, ATTENDANCE_ADMIN_EMAIL);
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL_C })).toBeVisible();
  const id = unique();
  // The same year the attendance tests use (whichever test creates it first).
  const yearId = await yearNamed(page, {
    name: "E2E now",
    starts_on: kenyaDate(-60),
    ends_on: kenyaDate(200),
    terms: [{ number: 1, starts_on: kenyaDate(-60), ends_on: kenyaDate(100) }],
  });
  const classId = await newClass(page, yearId, `M${id}`);
  const student = await call(page, "POST", "/school/students", {
    admission_number: `M${id}-1`,
    full_name: `Amani ${id}`,
  });
  expect(student.status).toBe(201);
  const studentId = (student.json.student as { id: string }).id;
  expect((await call(page, "POST", `/school/classes/${classId}/students`, { student_ids: [studentId] })).status).toBe(
    201,
  );
  const music = await newSubject(page, `Music ${id}`);
  expect((await call(page, "POST", `/school/classes/${classId}/subjects`, { subject_id: music })).status).toBe(201);
  const teacher = await teacherId(page, ATTENDANCE_TEACHER_EMAIL);
  const assigned = await call(page, "POST", `/school/classes/${classId}/subjects/${music}/teachers`, {
    membership_id: teacher,
  });
  expect(assigned.status).toBe(201);
  const className = `Grade 4 M${id}`;
  await logOut(page);

  await logIn(page, ATTENDANCE_TEACHER_EMAIL);
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL_C })).toBeVisible();
  await expect(page.getByRole("link", { name: "Subjects" })).toHaveCount(0);
  await page.getByRole("link", { name: "Classes" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "My classes" })).toBeVisible();
  await page.getByLabel("School year").selectOption({ label: "E2E now" });
  const row = page.getByRole("row", { name: new RegExp(`^${className}\\b`) });
  await expect(row).toContainText(`Music ${id}`);
  await expect(row).not.toContainText("Class teacher");

  await row.getByRole("link", { name: className }).click();
  await expect(page.getByRole("heading", { level: 1, name: className })).toBeVisible();
  await expect(page.getByText(`You teach Music ${id} in this class.`)).toBeVisible();
  await expect(page.getByRole("cell", { name: `Amani ${id}` })).toBeVisible();
  await expect(page.getByRole("link", { name: "Today's register" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Subjects" })).toHaveCount(0);

  // Only class teachers' classes appear on the attendance page.
  await page.getByRole("link", { name: "Attendance" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Attendance" })).toBeVisible();
  await expect(page.getByText("Loading...")).toHaveCount(0);
  await expect(page.getByRole("row", { name: new RegExp(`^${className}\\b`) })).toHaveCount(0);
});

test("a principal sees subjects and their teachers but changes nothing", async ({ page }) => {
  await logInToSchoolA(page);
  const id = unique();
  const yearId = await yearNamed(page, PAST_YEAR);
  const classId = await newClass(page, yearId, `P${id}`);
  const art = await newSubject(page, `Art ${id}`, `A${id}`);
  expect((await call(page, "POST", `/school/classes/${classId}/subjects`, { subject_id: art })).status).toBe(201);
  const teacher = await teacherId(page, TEACHER_EMAIL);
  expect(
    (await call(page, "POST", `/school/classes/${classId}/subjects/${art}/teachers`, { membership_id: teacher }))
      .status,
  ).toBe(201);
  await logOut(page);

  await logIn(page, PRINCIPAL_EMAIL);
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL_A })).toBeVisible();
  await expect(page.getByText("See subjects and who teaches them")).toBeVisible();
  await page.getByRole("link", { name: "Subjects" }).click();
  await expect(subjectRow(page, `Art ${id}`)).toContainText(`A${id}`);
  await expect(page.getByRole("button", { name: "Add a subject" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Edit / })).toHaveCount(0);

  await page.goto(`/classes/${classId}`);
  await expect(classSubject(page, `Art ${id}`)).toContainText("E2E Teacher");
  await expect(page.getByRole("button", { name: /^Remove / })).toHaveCount(0);
  await expect(page.getByLabel("Add a subject")).toHaveCount(0);
});

test("teachers have no subjects page", async ({ page }) => {
  await page.goto("/login");
  await logIn(page, TEACHER_EMAIL);
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL_A })).toBeVisible();

  await page.goto("/subjects");

  await expect(page.getByText(`You do not have access to this page in ${SCHOOL_A}.`)).toBeVisible();
});

test("the subject pages fit a phone screen without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await logInToSchoolA(page);
  const id = unique();
  const yearId = await yearNamed(page, PAST_YEAR);
  const classId = await newClass(page, yearId, `W${id}`);
  const name = `Agriculture and Nutrition ${id}`;
  const subject = await newSubject(page, name, `AGN${id}`.slice(0, 10));
  expect((await call(page, "POST", `/school/classes/${classId}/subjects`, { subject_id: subject })).status).toBe(201);

  for (const path of ["/subjects", `/classes/${classId}`]) {
    await page.goto(path);
    await expect(page.getByText(name).first()).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `${path} scrolls sideways`).toBe(0);
  }
});
