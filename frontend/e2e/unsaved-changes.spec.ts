import { expect, test, type Page } from "@playwright/test";

import { ATTENDANCE_ADMIN_EMAIL, SCHOOL_C, logIn } from "./helpers";

// A warning before unsaved work is lost, and the two-row header (D8), in
// E2E School C (see marks.spec.ts). All names are made up.

const LEAVE = "You have unsaved changes. Leave this page and lose them?";

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

async function logInAsAdmin(page: Page) {
  await page.goto("/login");
  await logIn(page, ATTENDANCE_ADMIN_EMAIL);
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

// Answers the next "unsaved changes" question, and remembers what was asked.
function answerNextQuestion(page: Page, accept: boolean): string[] {
  const asked: string[] = [];
  page.once("dialog", async (dialog) => {
    asked.push(`${dialog.type()}: ${dialog.message()}`);
    await (accept ? dialog.accept() : dialog.dismiss());
  });
  return asked;
}

// Fails the test if any question is asked.
function noQuestions(page: Page): string[] {
  const asked: string[] = [];
  page.on("dialog", async (dialog) => {
    asked.push(dialog.message());
    await dialog.dismiss();
  });
  return asked;
}

function menu(page: Page, name: string) {
  return page.getByRole("navigation", { name: "Main" }).getByRole("link", { name, exact: true });
}

test("an unsaved register asks before a menu link leaves it", async ({ page }) => {
  await logInAsAdmin(page);
  const c = await smallClass(page);
  await page.goto(`/classes/${c.classId}/attendance?date=${kenyaDate(0)}`);
  const amani = page.getByRole("group", { name: new RegExp(`^Amani ${c.id}`) });
  await amani.getByLabel("Late").check();

  // Cancel: still here, the choice kept.
  let asked = answerNextQuestion(page, false);
  await menu(page, "Classes").click();
  await expect.poll(() => asked).toEqual([`confirm: ${LEAVE}`]);
  await expect(page).toHaveURL(/\/attendance\?date=/);
  await expect(amani.getByLabel("Late")).toBeChecked();

  // OK: leaves.
  asked = answerNextQuestion(page, true);
  await menu(page, "Classes").click();
  await expect(page.getByRole("heading", { level: 1, name: "Classes" })).toBeVisible();
  expect(asked).toEqual([`confirm: ${LEAVE}`]);
});

test("unsaved marks ask before logging out; saved marks do not", async ({ page }) => {
  await logInAsAdmin(page);
  const c = await smallClass(page);
  await page.goto(`/assessments/${c.assessmentId}`);
  const score = page.getByLabel(new RegExp(`^Score for Amani ${c.id}`));
  await score.fill("7");

  const asked = answerNextQuestion(page, false);
  await page.getByRole("button", { name: "Log out" }).click();
  await expect.poll(() => asked).toEqual([`confirm: ${LEAVE}`]);
  await expect(score).toHaveValue("7");
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();

  // Saved: nothing asks any more.
  await page.getByRole("button", { name: "Save marks" }).click();
  await expect(page.getByRole("main").getByRole("status")).toHaveText("Marks saved.");
  const none = noQuestions(page);
  await menu(page, "Classes").click();
  await expect(page.getByRole("heading", { level: 1, name: "Classes" })).toBeVisible();
  expect(none).toEqual([]);
});

test("agreeing to log out with unsaved marks asks once, then logs out", async ({ page }) => {
  await logInAsAdmin(page);
  const c = await smallClass(page);
  await page.goto(`/assessments/${c.assessmentId}`);
  await page.getByLabel(new RegExp(`^Score for Amani ${c.id}`)).fill("7");

  const asked: string[] = [];
  page.on("dialog", async (dialog) => {
    asked.push(`${dialog.type()}: ${dialog.message()}`);
    await dialog.accept();
  });
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL("/login");
  // Only our question: the browser's own warning does not follow it.
  expect(asked).toEqual([`confirm: ${LEAVE}`]);
});

test("an unsaved comment asks before the term changes, and before the tab closes", async ({ page }) => {
  await logInAsAdmin(page);
  const c = await smallClass(page);
  await page.goto(`/classes/${c.classId}/report-cards?term=1`);
  const box = page.getByLabel(`Comment for Amani ${c.id}`);
  await box.fill("Reads well.");

  const asked = answerNextQuestion(page, false);
  await page.getByLabel("Term").selectOption("2");
  await expect.poll(() => asked).toEqual([`confirm: ${LEAVE}`]);
  await expect(page.getByLabel("Term")).toHaveValue("1");
  await expect(box).toHaveValue("Reads well.");

  // Closing the tab: the browser's own warning.
  const closing = answerNextQuestion(page, false);
  await page.close({ runBeforeUnload: true });
  await expect.poll(() => closing).toEqual(["beforeunload: "]);
});

// Next.js keeps visited pages alive in the background (cacheComponents), so
// "lose them" must really discard the typing, not just stop asking.
test("changes the person agreed to lose do not come back", async ({ page }) => {
  await logInAsAdmin(page);
  const c = await smallClass(page);
  const openClass = async () => {
    await menu(page, "Classes").click();
    // Wait for the Classes page: until it arrives, the page being left may
    // have its own link to the class.
    await expect(page.getByRole("heading", { level: 1, name: "Classes" })).toBeVisible();
    await page.getByRole("main").getByRole("link", { name: new RegExp(c.id) }).first().click();
  };

  // Marks.
  await page.goto(`/assessments/${c.assessmentId}`);
  const score = page.getByLabel(new RegExp(`^Score for Amani ${c.id}`));
  await score.fill("7");
  let asked = answerNextQuestion(page, true);
  await menu(page, "Classes").click();
  await expect(page.getByRole("heading", { level: 1, name: "Classes" })).toBeVisible();
  expect(asked).toEqual([`confirm: ${LEAVE}`]);
  await openClass();
  await page.getByRole("link", { name: `Mathematics ${c.id} marks` }).first().click();
  await page.getByRole("link", { name: "Quiz" }).click();
  await expect(score).toHaveValue("");

  // A report card comment.
  await openClass();
  await page.getByRole("link", { name: "Report cards" }).first().click();
  const box = page.getByLabel(`Comment for Amani ${c.id}`);
  await box.fill("Draft");
  asked = answerNextQuestion(page, true);
  await openClass();
  expect(asked).toEqual([`confirm: ${LEAVE}`]);
  await page.getByRole("link", { name: "Report cards" }).first().click();
  await expect(box).toHaveValue("");

  // A register.
  await openClass();
  await page.getByRole("link", { name: "Today's register" }).first().click();
  const amani = page.getByRole("group", { name: new RegExp(`^Amani ${c.id}`) });
  await amani.getByLabel("Late").check();
  asked = answerNextQuestion(page, true);
  await openClass();
  expect(asked).toEqual([`confirm: ${LEAVE}`]);
  await page.getByRole("link", { name: "Today's register" }).first().click();
  await expect(amani.getByLabel("Present")).toBeChecked();

  // Nothing is unsaved any more, so nothing asks.
  const none = noQuestions(page);
  await menu(page, "Classes").click();
  await expect(page.getByRole("heading", { level: 1, name: "Classes" })).toBeVisible();
  expect(none).toEqual([]);
});

test("nothing asks when nothing was changed", async ({ page }) => {
  await logInAsAdmin(page);
  const c = await smallClass(page);
  const asked = noQuestions(page);

  await page.goto(`/classes/${c.classId}/attendance?date=${kenyaDate(0)}`);
  const amani = page.getByRole("group", { name: new RegExp(`^Amani ${c.id}`) });
  // Changed and changed back is not a change.
  await amani.getByLabel("Late").check();
  await amani.getByLabel("Present").check();
  await menu(page, "Classes").click();
  await expect(page.getByRole("heading", { level: 1, name: "Classes" })).toBeVisible();

  await page.goto(`/classes/${c.classId}/report-cards?term=1`);
  await expect(page.getByLabel(`Comment for Amani ${c.id}`)).toBeVisible();
  await page.getByLabel("Term").selectOption("2");
  await expect(page).toHaveURL(/term=2/);
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL("/login");
  expect(asked).toEqual([]);
});

test("the header keeps the menu on its own row", async ({ page }) => {
  await logInAsAdmin(page);
  const rows = async () =>
    page.evaluate(() => {
      const top = (selector: string) => Math.round(document.querySelector(selector)!.getBoundingClientRect().top);
      const links = Array.from(document.querySelectorAll('nav[aria-label="Main"] li')).map((li) =>
        Math.round(li.getBoundingClientRect().top),
      );
      return {
        title: top("header p.font-semibold"),
        logOut: top("header button"),
        menuTops: [...new Set(links)].length,
        menuTop: links[0],
        overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      };
    });

  // Desktop: the app's name and Log out on one row, the whole menu on one
  // row below it.
  await page.setViewportSize({ width: 1024, height: 768 });
  const wide = await rows();
  expect(Math.abs(wide.title - wide.logOut)).toBeLessThan(12);
  expect(wide.menuTop).toBeGreaterThan(wide.title);
  expect(wide.menuTops).toBe(1);
  expect(wide.overflow).toBe(0);

  // The narrowest phone: the menu may wrap, but nothing runs off the screen.
  await page.setViewportSize({ width: 320, height: 740 });
  const narrow = await rows();
  expect(narrow.menuTop).toBeGreaterThan(narrow.title);
  expect(narrow.overflow).toBe(0);
});
