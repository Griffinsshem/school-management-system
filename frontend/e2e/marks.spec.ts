import { expect, test, type Page } from "@playwright/test";

import { ATTENDANCE_ADMIN_EMAIL, ATTENDANCE_TEACHER_EMAIL, SCHOOL_C, errorMessage, logIn } from "./helpers";

// Assessments and marks (D4), in E2E School C, whose school year is around
// today (marks can only be dated inside a term, up to today). Each test makes
// its own class, students and subject, so tests do not depend on each other.

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

async function logOut(page: Page) {
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL("/login");
}

function notice(page: Page) {
  return page.getByRole("main").getByRole("status");
}

// School C's year around today, shared with the attendance tests (the same
// shape, whichever test creates it first).
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

// A class of three students taking a new subject, set up by School C's
// administrator (logged in). The teacher is the subject's teacher, or the
// class teacher.
async function classWithSubject(page: Page, teacherIs: "subject" | "class") {
  const id = unique();
  const yearId = await currentYear(page);
  const made = await call(page, "POST", "/school/classes", { academic_year_id: yearId, grade: "grade_5", stream: id });
  expect(made.status).toBe(201);
  const classId = (made.json.class as { id: string }).id;
  const students: Record<string, string> = {};
  for (const [n, first] of ["Amani", "Baraka", "Chausiku"].entries()) {
    const student = await call(page, "POST", "/school/students", {
      admission_number: `K${id}-${n + 1}`,
      full_name: `${first} ${id}`,
    });
    expect(student.status).toBe(201);
    students[first] = (student.json.student as { id: string }).id;
  }
  const enrolled = await call(page, "POST", `/school/classes/${classId}/students`, {
    student_ids: Object.values(students),
  });
  expect(enrolled.status).toBe(201);
  const subject = await call(page, "POST", "/school/subjects", { name: `Science ${id}` });
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
  return { id, classId, className: `Grade 5 ${id}`, subjectId, subject: `Science ${id}`, students };
}

function scoreBox(page: Page, first: string, id: string) {
  return page.getByLabel(new RegExp(`^Score for ${first} ${id}`));
}

function studentRow(page: Page, first: string, id: string) {
  return page.getByRole("listitem").filter({ hasText: `${first} ${id}` });
}

test("a logged-out visitor is sent to the login page", async ({ page }) => {
  const nobody = "00000000-0000-0000-0000-000000000000";
  await page.goto(`/assessments/${nobody}`);
  await expect(page).toHaveURL(`/login?next=%2Fassessments%2F${nobody}`);
  await page.goto(`/classes/${nobody}/marks`);
  await expect(page).toHaveURL(`/login?next=%2Fclasses%2F${nobody}%2Fmarks`);
});

test("a subject teacher adds an assessment and enters marks; a lock stops changes", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const c = await classWithSubject(page, "subject");
  await logOut(page);

  await logInAs(page, ATTENDANCE_TEACHER_EMAIL);
  await expect(page.getByText("Enter marks for the subjects you teach")).toBeVisible();
  await page.getByRole("link", { name: "Classes" }).click();
  await page.getByRole("row", { name: new RegExp(`^${c.className}\\b`) }).getByRole("link").click();
  await expect(page.getByText(`You teach ${c.subject} in this class.`)).toBeVisible();
  await expect(page.getByRole("link", { name: "Marks overview" })).toHaveCount(0);
  await page.getByRole("link", { name: `${c.subject} marks` }).click();
  await expect(page.getByRole("heading", { level: 1, name: `${c.subject} marks` })).toBeVisible();
  await expect(page.getByText("No assessments in Term 1 yet.")).toBeVisible();

  // Mistakes in the form are explained.
  await page.getByRole("button", { name: "Add an assessment" }).click();
  await expect(page.getByRole("heading", { name: "Add an assessment to Term 1" })).toBeFocused();
  await page.getByRole("button", { name: "Add assessment" }).click();
  await expect(errorMessage(page)).toHaveText("Enter the assessment's name, such as Mid-term.");
  await page.getByLabel(/^Name/).fill("Mid-term");
  await page.getByLabel("Out of").fill("20");
  await page.getByRole("button", { name: "Add assessment" }).click();
  await expect(notice(page)).toHaveText("Added Mid-term. Open it to enter marks.");
  await expect(page.getByRole("row", { name: /^Mid-term/ })).toContainText("0 of 3");

  // The mark sheet: a score above the maximum is caught before saving.
  await page.getByRole("link", { name: "Mid-term" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mid-term" })).toBeVisible();
  await scoreBox(page, "Amani", c.id).fill("15");
  await scoreBox(page, "Baraka", c.id).fill("25");
  await studentRow(page, "Chausiku", c.id).getByLabel("Did not sit").check();
  await page.getByRole("button", { name: "Save marks" }).click();
  await expect(errorMessage(page)).toHaveText(`Baraka ${c.id}: The highest score is 20.`);
  await scoreBox(page, "Baraka", c.id).fill("12.5");
  await expect(page.getByText("3 of 3 entered, 1 did not sit. Average 13.8 out of 20 (69%).")).toBeVisible();
  await page.getByRole("button", { name: "Save marks" }).click();
  await expect(notice(page)).toHaveText("Marks saved.");

  // Saved for real.
  await page.reload();
  await expect(scoreBox(page, "Baraka", c.id)).toHaveValue("12.5");
  await expect(studentRow(page, "Chausiku", c.id).getByLabel("Did not sit")).toBeChecked();
  await expect(page.getByRole("button", { name: "Lock" })).toHaveCount(0);
  const sheetUrl = page.url();
  await logOut(page);

  // The administrator locks it; the teacher can then only read it.
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  await page.goto(sheetUrl);
  await page.getByRole("button", { name: "Lock", exact: true }).click();
  await expect(notice(page)).toHaveText("Locked: only school administrators can change these marks now.");
  await logOut(page);

  await logInAs(page, ATTENDANCE_TEACHER_EMAIL);
  await page.goto(sheetUrl);
  await expect(page.getByText("Locked: only school administrators can change these marks.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save marks" })).toHaveCount(0);
  await expect(page.getByRole("row", { name: new RegExp(`^K${c.id}-1`) })).toContainText("15 (75%)");
});

test("the class teacher reads every subject's marks but changes none", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const c = await classWithSubject(page, "class");
  const created = await call(page, "POST", `/school/classes/${c.classId}/subjects/${c.subjectId}/assessments`, {
    term: 1,
    name: "Opener",
    max_score: 40,
    held_on: kenyaDate(0),
  });
  expect(created.status).toBe(201);
  const assessment = (created.json.assessment as { id: string }).id;
  const saved = await call(page, "PUT", `/school/assessments/${assessment}/marks`, {
    marks: [
      { student_id: c.students.Amani, score: 30 },
      { student_id: c.students.Baraka, did_not_sit: true },
    ],
  });
  expect(saved.status).toBe(200);
  await logOut(page);

  await logInAs(page, ATTENDANCE_TEACHER_EMAIL);
  await page.getByRole("link", { name: "Classes" }).click();
  await page.getByRole("row", { name: new RegExp(`^${c.className}\\b`) }).getByRole("link").click();
  await page.getByRole("link", { name: "Marks overview" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Marks overview" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: `${c.subject}: Opener` })).toBeVisible();
  await expect(page.getByRole("row", { name: new RegExp(`^Amani ${c.id}`) })).toContainText("30 (75%)");
  await expect(page.getByRole("row", { name: new RegExp(`^Baraka ${c.id}`) })).toContainText("Did not sit");
  await expect(page.getByRole("row", { name: new RegExp(`^Chausiku ${c.id}`) })).toContainText("Not entered");

  await page.getByRole("link", { name: `${c.subject}: Opener` }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Opener" })).toBeVisible();
  await expect(page.getByText("2 of 3 entered, 1 did not sit. Average 30.0 out of 40 (75%).")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save marks" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Edit details" })).toHaveCount(0);
});

test("an administrator cannot remove a subject that has assessments", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const c = await classWithSubject(page, "subject");
  const created = await call(page, "POST", `/school/classes/${c.classId}/subjects/${c.subjectId}/assessments`, {
    term: 1,
    name: "CAT 1",
    max_score: 10,
    held_on: kenyaDate(0),
  });
  expect(created.status).toBe(201);

  await page.goto(`/classes/${c.classId}`);
  await page.getByRole("button", { name: `Remove ${c.subject} from ${c.className}` }).click();
  await page.getByRole("button", { name: "Yes, remove" }).click();

  await expect(errorMessage(page)).toHaveText(`${c.subject} has assessments in this class, so it cannot be removed.`);
  await expect(page.getByRole("link", { name: `${c.subject} marks` })).toBeVisible();
});

test("the mark sheet and overview fit a phone screen without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const c = await classWithSubject(page, "class");
  const created = await call(page, "POST", `/school/classes/${c.classId}/subjects/${c.subjectId}/assessments`, {
    term: 1,
    name: "End of term examination",
    max_score: 100,
    held_on: kenyaDate(0),
  });
  const assessment = (created.json.assessment as { id: string }).id;

  for (const path of [`/assessments/${assessment}`, `/classes/${c.classId}/marks?term=1`]) {
    await page.goto(path);
    await expect(page.getByText(`Amani ${c.id}`).first()).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `${path} scrolls sideways`).toBe(0);
  }
});
