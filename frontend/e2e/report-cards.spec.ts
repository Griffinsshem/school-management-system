import { expect, test, type Page } from "@playwright/test";

import { ATTENDANCE_ADMIN_EMAIL, ATTENDANCE_TEACHER_EMAIL, SCHOOL_C, errorMessage, logIn } from "./helpers";

// Report cards and class teachers' comments (D7), in E2E School C (see
// marks.spec.ts and results.spec.ts). All names and comments are made up.

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

// School C's year around today, shared with the attendance, marks and results tests.
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

// A Grade 5 class with three students, Mathematics and English, set up by
// School C's administrator (logged in). The teacher is the class teacher, or
// teaches Mathematics only. Amani has marks in both subjects; Baraka in
// Mathematics only; Chausiku none.
async function gradeFive(page: Page, teacherIs: "class" | "subject") {
  const id = unique();
  const yearId = await currentYear(page);
  const made = await call(page, "POST", "/school/classes", { academic_year_id: yearId, grade: "grade_5", stream: id });
  expect(made.status).toBe(201);
  const classId = (made.json.class as { id: string }).id;
  const students: Record<string, string> = {};
  for (const [n, first] of ["Amani", "Baraka", "Chausiku"].entries()) {
    const student = await call(page, "POST", "/school/students", {
      admission_number: `RC${id}-${n + 1}`,
      full_name: `${first} ${id}`,
    });
    expect(student.status).toBe(201);
    students[first] = (student.json.student as { id: string }).id;
  }
  const enrolled = await call(page, "POST", `/school/classes/${classId}/students`, {
    student_ids: Object.values(students),
  });
  expect(enrolled.status).toBe(201);
  const subjects: Record<string, string> = {};
  for (const name of ["Mathematics", "English"]) {
    const subject = await call(page, "POST", "/school/subjects", { name: `${name} ${id}` });
    expect(subject.status).toBe(201);
    subjects[name] = (subject.json.subject as { id: string }).id;
    expect((await call(page, "POST", `/school/classes/${classId}/subjects`, { subject_id: subjects[name] })).status).toBe(
      201,
    );
    const exam = await call(page, "POST", `/school/classes/${classId}/subjects/${subjects[name]}/assessments`, {
      term: 1,
      name: "Exam",
      max_score: 100,
      held_on: kenyaDate(0),
    });
    expect(exam.status).toBe(201);
    const examId = (exam.json.assessment as { id: string }).id;
    const marks = [{ student_id: students.Amani, score: name === "Mathematics" ? 64 : 80 }];
    if (name === "Mathematics") {
      marks.push({ student_id: students.Baraka, score: 50 });
    }
    expect((await call(page, "PUT", `/school/assessments/${examId}/marks`, { marks })).status).toBe(200);
  }
  const assign =
    teacherIs === "class"
      ? `/school/classes/${classId}/teachers`
      : `/school/classes/${classId}/subjects/${subjects.Mathematics}/teachers`;
  expect((await call(page, "POST", assign, { membership_id: await teacherMembership(page) })).status).toBe(201);
  return { id, classId, students };
}

async function takeRegister(page: Page, classId: string, students: Record<string, string>) {
  const register = await call(page, "PUT", `/school/classes/${classId}/attendance/${kenyaDate(0)}`, {
    marks: [
      { student_id: students.Amani, status: "present" },
      { student_id: students.Baraka, status: "late" },
      { student_id: students.Chausiku, status: "absent", reason: "sick" },
    ],
  });
  expect([200, 201]).toContain(register.status);
}

function studentItem(page: Page, first: string, id: string) {
  return page.getByRole("listitem").filter({ has: page.getByRole("heading", { level: 2, name: `${first} ${id}` }) });
}

test("a logged-out visitor is sent to the login page", async ({ page }) => {
  const nobody = "00000000-0000-0000-0000-000000000000";
  for (const path of [`/classes/${nobody}/report-cards`, `/classes/${nobody}/report-cards/${nobody}`]) {
    await page.goto(path);
    await expect(page).toHaveURL(`/login?next=${encodeURIComponent(path)}`);
  }
});

test("the class teacher writes comments that appear on the report card", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const c = await gradeFive(page, "class");
  await takeRegister(page, c.classId, c.students);
  await logOut(page);

  await logInAs(page, ATTENDANCE_TEACHER_EMAIL);
  await page.goto(`/classes/${c.classId}`);
  await page.getByRole("link", { name: "Report cards" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Report cards" })).toBeVisible();
  await expect(page.getByText("0 of 3 comments written.")).toBeVisible();
  const amani = studentItem(page, "Amani", c.id);
  // ME1 (6 points) and EE2 (7): an average of 6.5, rounded half up to 7.
  await expect(amani).toContainText("Overall: EE2");
  await expect(studentItem(page, "Baraka", c.id)).toContainText("(incomplete)");
  await expect(studentItem(page, "Chausiku", c.id)).toContainText("no results yet");

  // Only spaces, or too long, is explained before anything is sent.
  const sent: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "PUT" && request.url().includes("/comment")) {
      sent.push(request.url());
    }
  });
  const box = page.getByLabel(`Comment for Amani ${c.id}`);
  const save = page.getByRole("button", { name: `Save comment for Amani ${c.id}` });
  await box.fill("   ");
  await save.click();
  await expect(errorMessage(page)).toHaveText("A comment cannot be only spaces. Leave it empty to clear it.");
  await box.fill("x".repeat(501));
  await expect(amani).toContainText("501 of 500 characters");
  await save.click();
  await expect(errorMessage(page)).toHaveText("A comment can be at most 500 characters (this one has 501).");
  expect(sent).toHaveLength(0);

  // Saved trimmed, with its line break.
  await box.fill("  Amani reads widely.\nKeep it up next term.  ");
  await save.click();
  await expect(amani.getByRole("status")).toHaveText(`Comment saved for Amani ${c.id}.`);
  await expect(box).toHaveValue("Amani reads widely.\nKeep it up next term.");
  await expect(amani).toContainText("Last changed by");
  await expect(page.getByText("1 of 3 comments written.")).toBeVisible();
  await expect(save).toBeDisabled();

  // Kept after a reload, and on the report card.
  await page.reload();
  await expect(page.getByLabel(`Comment for Amani ${c.id}`)).toHaveValue("Amani reads widely.\nKeep it up next term.");
  await page.getByRole("link", { name: `View report card of Amani ${c.id}` }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Report card" })).toBeVisible();
  const card = page.getByRole("article");
  await expect(card).toContainText(SCHOOL_C);
  await expect(card).toContainText("Term 1 report, E2E now");
  await expect(card.getByRole("heading", { level: 2, name: `Amani ${c.id}` })).toBeVisible();
  await expect(card.getByRole("row", { name: new RegExp(`^Mathematics ${c.id}`) })).toContainText("64%");
  await expect(card.getByRole("row", { name: new RegExp(`^English ${c.id}`) })).toContainText("EE2");
  await expect(card).toContainText("Present 1, late 0, absent 0, out of 1 day recorded");
  await expect(card).toContainText("Amani reads widely.");
  await expect(page.getByRole("button", { name: "Print" })).toBeVisible();

  // Cleared by saving it empty.
  await page.getByRole("link", { name: "Back to the report cards" }).click();
  await page.getByLabel(`Comment for Amani ${c.id}`).fill("");
  await page.getByRole("button", { name: `Save comment for Amani ${c.id}` }).click();
  await expect(studentItem(page, "Amani", c.id).getByRole("status")).toHaveText(`Comment removed for Amani ${c.id}.`);
  await expect(page.getByText("0 of 3 comments written.")).toBeVisible();
});

test("all report cards print one per page, without the menu or buttons", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const c = await gradeFive(page, "class");
  const comment = await call(page, "PUT", `/school/classes/${c.classId}/report-cards/${c.students.Baraka}/comment?term=1`, {
    comment: "Baraka has settled in well.",
  });
  expect(comment.status).toBe(200);

  await page.goto(`/classes/${c.classId}/report-cards?term=1`);
  await page.getByRole("link", { name: "Print all report cards" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Print report cards" })).toBeVisible();
  const cards = page.getByRole("article");
  await expect(cards).toHaveCount(3);
  await expect(cards.filter({ hasText: `Baraka ${c.id}` })).toContainText("Baraka has settled in well.");
  await expect(cards.filter({ hasText: `Chausiku ${c.id}` })).toContainText("No comment yet.");
  await expect(cards.filter({ hasText: `Chausiku ${c.id}` })).toContainText("No registers recorded this term");

  await page.emulateMedia({ media: "print" });
  await expect(page.getByRole("banner").first()).toBeHidden();
  await expect(page.getByRole("button", { name: "Print all" })).toBeHidden();
  await expect(page.getByRole("button", { name: "Log out" })).toBeHidden();
  const breaks = await cards.evaluateAll((articles) =>
    articles.map((article) => getComputedStyle(article.parentElement as Element).breakAfter),
  );
  expect(breaks).toEqual(["page", "page", "page"]);

  // Dark text on white paper, even when the screen is dark.
  await page.emulateMedia({ media: "print", colorScheme: "dark" });
  expect(await page.evaluate(() => getComputedStyle(document.body).color)).toBe("rgb(23, 23, 23)");
});

test("a subject teacher has no report cards; others' cards are not found", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const c = await gradeFive(page, "subject");
  await logOut(page);

  await logInAs(page, ATTENDANCE_TEACHER_EMAIL);
  await page.goto(`/classes/${c.classId}`);
  await expect(page.getByText(`You teach Mathematics ${c.id} in this class.`)).toBeVisible();
  await expect(page.getByRole("link", { name: "Report cards" })).toHaveCount(0);
  await page.goto(`/classes/${c.classId}/report-cards`);
  await expect(page.getByRole("heading", { level: 1, name: "Report cards not found" })).toBeVisible();
  await page.goto(`/classes/${c.classId}/report-cards/${c.students.Amani}`);
  await expect(page.getByRole("heading", { level: 1, name: "Report card not found" })).toBeVisible();
  await page.goto(`/classes/${c.classId}/report-cards/print`);
  await expect(page.getByRole("heading", { level: 1, name: "Report cards not found" })).toBeVisible();
});

test("report cards fit a phone screen without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const c = await gradeFive(page, "class");

  for (const path of [
    `/classes/${c.classId}/report-cards?term=1`,
    `/classes/${c.classId}/report-cards/${c.students.Amani}?term=1`,
    `/classes/${c.classId}/report-cards/print?term=1`,
  ]) {
    await page.goto(path);
    await expect(page.getByText(`Amani ${c.id}`).first()).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, path).toBe(0);
  }
});
