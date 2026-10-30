import { expect, test, type Page } from "@playwright/test";

import { ATTENDANCE_ADMIN_EMAIL, ATTENDANCE_TEACHER_EMAIL, SCHOOL_C, errorMessage, logIn } from "./helpers";

// Term results (D6): weights, the overall result and class positions, in
// E2E School C (see marks.spec.ts). Class positions are a school setting, so
// the test that switches them on switches them off again, even when it fails.

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

async function teacherMembership(page: Page): Promise<string> {
  const { json } = await call(page, "GET", "/school/members");
  const teacher = (json.members as { id: string; role: string; user: { email: string } }[]).find(
    (m) => m.user.email === ATTENDANCE_TEACHER_EMAIL && m.role === "teacher",
  );
  return teacher?.id ?? "";
}

// A class of the given grade level with three students and new subjects, set
// up by School C's administrator (logged in). The teacher is the class
// teacher, or the first subject's teacher.
async function classWithSubjects(page: Page, grade: string, subjects: string[], teacherIs: "class" | "subject") {
  const id = unique();
  const yearId = await currentYear(page);
  const made = await call(page, "POST", "/school/classes", { academic_year_id: yearId, grade, stream: id });
  expect(made.status).toBe(201);
  const classId = (made.json.class as { id: string }).id;
  const students: Record<string, string> = {};
  for (const [n, first] of ["Amani", "Baraka", "Chausiku"].entries()) {
    const student = await call(page, "POST", "/school/students", {
      admission_number: `R${id}-${n + 1}`,
      full_name: `${first} ${id}`,
    });
    expect(student.status).toBe(201);
    students[first] = (student.json.student as { id: string }).id;
  }
  expect(
    (await call(page, "POST", `/school/classes/${classId}/students`, { student_ids: Object.values(students) })).status,
  ).toBe(201);
  const subjectIds: Record<string, string> = {};
  for (const name of subjects) {
    const subject = await call(page, "POST", "/school/subjects", { name: `${name} ${id}` });
    expect(subject.status).toBe(201);
    subjectIds[name] = (subject.json.subject as { id: string }).id;
    const added = await call(page, "POST", `/school/classes/${classId}/subjects`, { subject_id: subjectIds[name] });
    expect(added.status).toBe(201);
  }
  const membership = await teacherMembership(page);
  const assign =
    teacherIs === "class"
      ? `/school/classes/${classId}/teachers`
      : `/school/classes/${classId}/subjects/${subjectIds[subjects[0]]}/teachers`;
  expect((await call(page, "POST", assign, { membership_id: membership })).status).toBe(201);
  return { id, classId, subjects: subjectIds, students };
}

async function exam(page: Page, classId: string, subjectId: string, name: string, max: number, weight?: number) {
  const created = await call(page, "POST", `/school/classes/${classId}/subjects/${subjectId}/assessments`, {
    term: 1,
    name,
    max_score: max,
    held_on: kenyaDate(0),
    ...(weight === undefined ? {} : { weight }),
  });
  expect(created.status).toBe(201);
  return (created.json.assessment as { id: string }).id;
}

async function marks(page: Page, assessment: string, entries: { student_id: string; score?: number; did_not_sit?: boolean }[]) {
  expect((await call(page, "PUT", `/school/assessments/${assessment}/marks`, { marks: entries })).status).toBe(200);
}

function row(page: Page, first: string, id: string) {
  return page.getByRole("row", { name: new RegExp(`${first} ${id}`) });
}

test("a logged-out visitor is sent to the login page", async ({ page }) => {
  const nobody = "00000000-0000-0000-0000-000000000000";
  await page.goto(`/classes/${nobody}/results`);
  await expect(page).toHaveURL(`/login?next=%2Fclasses%2F${nobody}%2Fresults`);
});

test("weights that make 100% weight the term result; others fall back to raw totals", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const c = await classWithSubjects(page, "grade_5", ["Science"], "class");
  const science = c.subjects.Science;

  // Add the CAT from the page, with a weight; a wrong weight is explained first.
  await page.goto(`/classes/${c.classId}/subjects/${science}/marks`);
  await page.getByRole("button", { name: "Add an assessment" }).click();
  await page.getByLabel("Name").fill("CAT");
  await page.getByLabel("Out of").fill("10");
  await page.getByLabel(/^Weight %/).fill("abc");
  await page.getByRole("button", { name: "Add assessment" }).click();
  await expect(errorMessage(page)).toContainText("A weight is a whole number from 1 to 100");
  await page.getByLabel(/^Weight %/).fill("30");
  await page.getByRole("button", { name: "Add assessment" }).click();
  await expect(notice(page)).toContainText("Added CAT.");
  await expect(page.getByText("The weights add up to 30%")).toBeVisible();

  // With the exam at 70%, the weights make 100%.
  const cat = await page
    .getByRole("link", { name: "CAT" })
    .getAttribute("href")
    .then((href) => href!.split("/").pop()!);
  const final = await exam(page, c.classId, science, "Exam", 50, 70);
  await page.reload();
  await expect(page.getByText("The weights add up to 100%: Term 1 results count each assessment by its weight.")).toBeVisible();
  await expect(page.getByRole("row", { name: /^CAT/ })).toContainText("30%");

  // CAT 5/10 (50%) and Exam 40/50 (80%): 0.3 x 50 + 0.7 x 80 = 71%, ME1.
  await marks(page, cat, [{ student_id: c.students.Amani, score: 5 }]);
  await marks(page, final, [{ student_id: c.students.Amani, score: 40 }]);
  await logOut(page);

  // The class teacher sees the weighted result, in the overview and the results.
  await logInAs(page, ATTENDANCE_TEACHER_EMAIL);
  await page.goto(`/classes/${c.classId}/marks`);
  await expect(page.getByRole("columnheader", { name: `Science ${c.id}: Term 1 weighted` })).toBeVisible();
  await expect(row(page, "Amani", c.id).getByRole("cell").nth(2)).toHaveText("71% ME1");
  await page.getByRole("link", { name: "Term results" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Term results" })).toBeVisible();
  await expect(row(page, "Amani", c.id)).toContainText("71% ME1");
});

test("a Form class's results give a KCSE mean grade, and positions only when switched on", async ({ page }) => {
  const names = ["Mathematics", "English", "Biology", "Chemistry", "History", "Geography", "Business"];
  try {
    await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
    const c = await classWithSubjects(page, "form_4", names, "class");

    // Mathematics is set from the Subjects page; English through the API.
    await page.goto("/subjects");
    await page.getByRole("button", { name: `Edit Mathematics ${c.id}` }).click();
    await page.getByLabel("Counts in a Form student's KCSE mean grade as").selectOption("mathematics");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(notice(page)).toHaveText(`Saved Mathematics ${c.id}.`);
    // Code, status, then the KCSE category.
    const mathsRow = page.getByRole("row", { name: new RegExp(`^Mathematics ${c.id}`) });
    await expect(mathsRow.getByRole("cell").nth(2)).toHaveText("Mathematics");
    const english = await call(page, "PATCH", `/school/subjects/${c.subjects.English}`, { kcse_category: "language" });
    expect(english.status).toBe(200);

    // Amani: 70% everywhere (B+, 10 points). Baraka: no Mathematics.
    // Chausiku: sat nothing.
    for (const name of names) {
      const id = await exam(page, c.classId, c.subjects[name], "Exam", 100);
      await marks(page, id, [
        { student_id: c.students.Amani, score: 70 },
        ...(name === "Mathematics" ? [] : [{ student_id: c.students.Baraka, score: 70 }]),
        { student_id: c.students.Chausiku, did_not_sit: true },
      ]);
    }

    await page.goto(`/classes/${c.classId}/results`);
    await expect(page.getByRole("columnheader", { name: "Mean grade" })).toBeVisible();
    const amani = row(page, "Amani", c.id);
    await expect(amani).toContainText("B+");
    await expect(amani).toContainText("70 points, 7 subjects");
    await expect(amani).not.toContainText("incomplete");
    await expect(row(page, "Baraka", c.id)).toContainText("(incomplete)");
    await expect(page.getByRole("columnheader", { name: "Position" })).toHaveCount(0);

    // Switched on from the Grading page: Amani is first; Baraka gets none.
    await page.goto("/grading");
    await page.getByLabel("Show class positions on term results").check();
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(notice(page)).toHaveText("Class positions are now shown on term results.");
    await page.goto(`/classes/${c.classId}/results`);
    await expect(page.getByRole("columnheader", { name: "Position" })).toBeVisible();
    await expect(row(page, "Amani", c.id).getByRole("cell").first()).toHaveText("1");
    await expect(row(page, "Baraka", c.id).getByRole("cell").first()).toHaveText("—");
  } finally {
    await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
    const off = await call(page, "PUT", "/school/grading/positions", { show_class_positions: false });
    expect(off.status).toBe(200);
  }
});

test("a subject teacher has no results page; teachers read the positions setting", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const c = await classWithSubjects(page, "grade_5", ["Music"], "subject");
  await logOut(page);

  await logInAs(page, ATTENDANCE_TEACHER_EMAIL);
  await page.goto(`/classes/${c.classId}`);
  await expect(page.getByText(`You teach Music ${c.id} in this class.`)).toBeVisible();
  await expect(page.getByRole("link", { name: "Term results" })).toHaveCount(0);
  await page.goto(`/classes/${c.classId}/results`);
  await expect(page.getByRole("heading", { level: 1, name: "Results not found" })).toBeVisible();

  await page.goto("/grading");
  await expect(page.getByText("Term results do not show class positions.")).toBeVisible();
  await expect(page.getByLabel("Show class positions on term results")).toHaveCount(0);
});

test("the results page fits a phone screen without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const c = await classWithSubjects(page, "grade_5", ["Science", "Kiswahili", "Social Studies"], "class");
  for (const subject of Object.values(c.subjects)) {
    const id = await exam(page, c.classId, subject, "End of term examination", 100);
    await marks(page, id, [{ student_id: c.students.Amani, score: 64 }]);
  }

  await page.goto(`/classes/${c.classId}/results`);
  await expect(row(page, "Amani", c.id)).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBe(0);
});
