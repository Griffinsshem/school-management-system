import { expect, test, type Page } from "@playwright/test";

import { PRINCIPAL_EMAIL, TEACHER_EMAIL, errorMessage, logIn, logInToSchoolA } from "./helpers";

// A past school year, so it never overlaps the years the school-year tests
// create around today. In 2025 Kenya had Grades up to 9 and Forms 2 to 4.
const YEAR = { name: "E2E 2025", starts_on: "2025-01-06", ends_on: "2025-11-28" };

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

// The 2025 year's ID, creating the year the first time.
async function year2025(page: Page): Promise<string> {
  const { json } = await call(page, "GET", "/school/academic-years");
  const years = json.academic_years as { id: string; name: string }[];
  const existing = years.find((year) => year.name === YEAR.name);
  if (existing) {
    return existing.id;
  }
  const created = await call(page, "POST", "/school/academic-years", YEAR);
  expect(created.status).toBe(201);
  return (created.json.academic_year as { id: string }).id;
}

// Each test uses its own stream, so tests do not depend on each other.
function stream(): string {
  return `T${Date.now().toString(36).slice(-6).toUpperCase()}`;
}

async function openClasses(page: Page, heading = "Classes") {
  await page.getByRole("link", { name: "Classes" }).click();
  await expect(page).toHaveURL("/classes");
  await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
}

function row(page: Page, name: string) {
  return page.getByRole("table").getByRole("row", { name: new RegExp(`^${name}\\b`) });
}

function notice(page: Page) {
  return page.getByRole("main").getByRole("status");
}

test("a logged-out visitor is sent to the login page", async ({ page }) => {
  await page.goto("/classes");

  await expect(page).toHaveURL("/login?next=%2Fclasses");
});

test("an administrator adds a class, changes it and chooses its class teachers", async ({ page }) => {
  await logInToSchoolA(page);
  await year2025(page);
  const name = stream();
  await openClasses(page);
  await page.getByLabel("School year").selectOption({ label: YEAR.name });

  await page.getByRole("button", { name: "Add a class" }).click();
  await expect(page.getByRole("heading", { name: `Add a class to ${YEAR.name}` })).toBeFocused();
  // Only the grades of 2025: Grade 9 and Form 2, but no Grade 10 or Form 1.
  const grades = page.getByLabel("Grade", { exact: true });
  await expect(grades.getByRole("option", { name: "Grade 9" })).toHaveCount(1);
  await expect(grades.getByRole("option", { name: "Form 2" })).toHaveCount(1);
  await expect(grades.getByRole("option", { name: "Grade 10" })).toHaveCount(0);
  await expect(grades.getByRole("option", { name: "Form 1" })).toHaveCount(0);

  await page.getByRole("button", { name: "Add class" }).click();
  await expect(errorMessage(page)).toHaveText("Choose a grade.");
  await grades.selectOption({ label: "Grade 9" });
  await page.getByLabel(/Stream/).fill(name);
  await page.getByRole("button", { name: "Add class" }).click();
  await expect(notice(page)).toHaveText(`Added Grade 9 ${name}.`);
  await expect(row(page, `Grade 9 ${name}`)).toContainText("None yet");

  // The same class again is explained.
  await page.getByRole("button", { name: "Add a class" }).click();
  await page.getByLabel("Grade", { exact: true }).selectOption({ label: "Grade 9" });
  await page.getByLabel(/Stream/).fill(name);
  await page.getByRole("button", { name: "Add class" }).click();
  await expect(errorMessage(page)).toHaveText(`This school year already has Grade 9 ${name}.`);
  await page.getByRole("button", { name: "Cancel" }).click();

  // Class teachers are chosen from the school's active teachers.
  await page.getByRole("button", { name: `Edit Grade 9 ${name}` }).click();
  await page.getByLabel("Add a class teacher").selectOption({ label: "E2E Teacher" });
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(notice(page)).toHaveText(`E2E Teacher is now a class teacher of Grade 9 ${name}.`);
  await expect(row(page, `Grade 9 ${name}`)).toContainText("E2E Teacher");
  await expect(page.getByText("Every active teacher is already a class teacher")).toBeVisible();

  await page.getByRole("button", { name: `Remove E2E Teacher from Grade 9 ${name}` }).click();
  await expect(notice(page)).toHaveText(`E2E Teacher is no longer a class teacher of Grade 9 ${name}.`);
  await expect(row(page, `Grade 9 ${name}`)).toContainText("None yet");

  // Changing the grade and stream.
  await page.getByLabel("Grade", { exact: true }).selectOption({ label: "Form 2" });
  await page.getByLabel(/Stream/).fill(`${name}X`);
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(notice(page)).toHaveText(`Saved Form 2 ${name}X.`);
  await expect(row(page, `Form 2 ${name}X`)).toBeVisible();
  await expect(page.getByRole("heading", { name: /^Edit / })).toHaveCount(0);
});

test("a teacher sees only the classes they teach", async ({ page }) => {
  await logInToSchoolA(page);
  const yearId = await year2025(page);
  const name = stream();
  const created: string[] = [];
  for (const grade of ["grade_7", "grade_8"]) {
    const response = await call(page, "POST", "/school/classes", {
      academic_year_id: yearId,
      grade,
      stream: name,
    });
    expect(response.status).toBe(201);
    created.push((response.json.class as { id: string }).id);
  }
  const { json } = await call(page, "GET", "/school/members");
  const teacher = (json.members as { id: string; role: string; user: { email: string } }[]).find(
    (m) => m.user.email === TEACHER_EMAIL && m.role === "teacher",
  );
  const assigned = await call(page, "POST", `/school/classes/${created[0]}/teachers`, {
    membership_id: teacher?.id,
  });
  expect(assigned.status).toBe(201);
  await page.getByRole("button", { name: "Log out" }).click();

  await logIn(page, TEACHER_EMAIL);
  await expect(page.getByText("See the classes you teach")).toBeVisible();
  await openClasses(page, "My classes");
  await page.getByLabel("School year").selectOption({ label: YEAR.name });

  await expect(row(page, `Grade 7 ${name}`)).toContainText("E2E Teacher");
  await expect(row(page, `Grade 8 ${name}`)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Add a class" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Edit / })).toHaveCount(0);
});

test("a principal sees every class but cannot change them", async ({ page }) => {
  await page.goto("/login");
  await logIn(page, PRINCIPAL_EMAIL);
  await expect(page.getByText("See every class and its class teachers")).toBeVisible();
  await openClasses(page);
  // Wait for the classes themselves: buttons appear only once they load.
  await expect(page.getByRole("table")).toBeVisible();

  await expect(page.getByRole("button", { name: "Add a class" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Edit / })).toHaveCount(0);
  // Hiding the buttons is a convenience: the API refuses anyway.
  const { json } = await call(page, "GET", "/school/academic-years");
  const yearId = (json.academic_years as { id: string }[])[0]?.id;
  const response = await call(page, "POST", "/school/classes", {
    academic_year_id: yearId,
    grade: "grade_1",
  });
  expect(response.status).toBe(403);
});

test("the classes page fits a phone screen without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await logInToSchoolA(page);
  const yearId = await year2025(page);
  await call(page, "POST", "/school/classes", {
    academic_year_id: yearId,
    grade: "form_4",
    stream: "Long stream name xyz", // 20 characters, the most allowed
  });

  await page.goto("/classes");
  await page.getByLabel("School year").selectOption({ label: YEAR.name });
  await expect(page.getByRole("table")).toBeVisible();
  await page.getByRole("button", { name: /^Edit / }).first().click();
  await expect(page.getByRole("heading", { name: "Class teachers" })).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, "/classes scrolls sideways").toBe(0);
});

// Class lists (C3).

async function newStudents(page: Page, start: string, names: string[]): Promise<string[]> {
  const ids: string[] = [];
  for (const [i, name] of names.entries()) {
    const response = await call(page, "POST", "/school/students", {
      admission_number: `${start}-${i + 1}`,
      full_name: `${name} ${start}`,
    });
    expect(response.status).toBe(201);
    ids.push((response.json.student as { id: string }).id);
  }
  return ids;
}

async function newClass(page: Page, yearId: string, grade: string, name: string): Promise<string> {
  const response = await call(page, "POST", "/school/classes", {
    academic_year_id: yearId,
    grade,
    stream: name,
  });
  expect(response.status).toBe(201);
  return (response.json.class as { id: string }).id;
}

function studentRow(page: Page, text: string) {
  return page.getByRole("table").getByRole("row").filter({ hasText: text });
}

test("a logged-out visitor is sent to the login page from a class list", async ({ page }) => {
  await page.goto("/classes/00000000-0000-0000-0000-000000000000");

  await expect(page).toHaveURL(
    "/login?next=%2Fclasses%2F00000000-0000-0000-0000-000000000000",
  );
});

test("an administrator adds students to a class, moves one and removes one", async ({ page }) => {
  await logInToSchoolA(page);
  await expect(page.getByText("Add students to classes and move them")).toBeVisible();
  const yearId = await year2025(page);
  const name = stream();
  await newClass(page, yearId, "grade_6", name);
  await newClass(page, yearId, "grade_6", `${name}B`);
  await newStudents(page, name, ["Amani", "Baraka", "Chausiku"]);

  await openClasses(page);
  await page.getByLabel("School year").selectOption({ label: YEAR.name });
  await page.getByRole("link", { name: `Grade 6 ${name}`, exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: `Grade 6 ${name}` })).toBeVisible();
  await expect(page.getByText(`No students in Grade 6 ${name} yet.`)).toBeVisible();

  await page.getByRole("button", { name: "Add students" }).click();
  await expect(page.getByRole("heading", { name: `Add students to Grade 6 ${name}` })).toBeFocused();
  await page.getByLabel("Search by name or admission number").fill(name);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByText("3 students without a class.")).toBeVisible();
  await page.getByRole("checkbox", { name: `Amani ${name}` }).check();
  await page.getByRole("checkbox", { name: `Baraka ${name}` }).check();
  await page.getByRole("button", { name: "Add 2 students" }).click();

  await expect(notice(page)).toHaveText(`Added 2 students to Grade 6 ${name}.`);
  await expect(page.getByText("2 students", { exact: true })).toBeVisible();
  await expect(studentRow(page, `Amani ${name}`)).toContainText(`${name}-1`);
  // Only Chausiku still needs a class.
  await expect(page.getByText("1 student without a class.")).toBeVisible();
  await expect(page.getByRole("checkbox", { name: `Amani ${name}` })).toHaveCount(0);
  await page.getByRole("button", { name: "Close" }).click();

  await page.getByRole("button", { name: `Move Amani ${name} (${name}-1) to another class` }).click();
  await expect(page.getByLabel(`Move Amani ${name} to`)).toBeFocused();
  await page.getByLabel(`Move Amani ${name} to`).selectOption({ label: `Grade 6 ${name}B` });
  await page.getByRole("button", { name: "Move", exact: true }).click();
  await expect(notice(page)).toHaveText(`Moved Amani ${name} (${name}-1) to Grade 6 ${name}B.`);
  await expect(studentRow(page, `Amani ${name}`)).toHaveCount(0);

  await page.getByRole("button", { name: `Remove Baraka ${name} (${name}-2) from Grade 6 ${name}` }).click();
  await expect(page.getByRole("button", { name: "Yes, remove" })).toBeFocused();
  await page.getByRole("button", { name: "Yes, remove" }).click();
  await expect(notice(page)).toHaveText(`Removed Baraka ${name} (${name}-2) from Grade 6 ${name}.`);
  await expect(page.getByText(`No students in Grade 6 ${name} yet.`)).toBeVisible();
});

test("a teacher sees names and admission numbers of their own classes only", async ({ page }) => {
  await logInToSchoolA(page);
  const yearId = await year2025(page);
  const name = stream();
  const mine = await newClass(page, yearId, "grade_5", name);
  const other = await newClass(page, yearId, "grade_5", `${name}B`);
  const [amani] = await newStudents(page, name, ["Amani"]);
  expect((await call(page, "POST", `/school/classes/${mine}/students`, { student_ids: [amani] })).status).toBe(201);
  const { json } = await call(page, "GET", "/school/members");
  const teacher = (json.members as { id: string; role: string; user: { email: string } }[]).find(
    (m) => m.user.email === TEACHER_EMAIL && m.role === "teacher",
  );
  expect(
    (await call(page, "POST", `/school/classes/${mine}/teachers`, { membership_id: teacher?.id })).status,
  ).toBe(201);
  await page.getByRole("button", { name: "Log out" }).click();

  await logIn(page, TEACHER_EMAIL);
  await openClasses(page, "My classes");
  await page.getByLabel("School year").selectOption({ label: YEAR.name });
  await page.getByRole("link", { name: `Grade 5 ${name}`, exact: true }).click();

  await expect(studentRow(page, `Amani ${name}`)).toContainText(`${name}-1`);
  // Names and admission numbers only: no status column, no buttons.
  await expect(page.getByRole("columnheader")).toHaveText(["Admission no.", "Name"]);
  await expect(page.getByRole("button", { name: "Add students" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^(Move|Remove) / })).toHaveCount(0);

  // Another class's list is not shown, exactly like a class that does not exist.
  await page.goto(`/classes/${other}`);
  await expect(page.getByRole("heading", { name: "Class not found" })).toBeVisible();
});

test("a class list fits a phone screen without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await logInToSchoolA(page);
  const yearId = await year2025(page);
  const name = stream();
  const classId = await newClass(page, yearId, "grade_4", name);
  const ids = await newStudents(page, name, ["Wanjiku Nyambura Kamau", "Otieno"]);
  await call(page, "POST", `/school/classes/${classId}/students`, { student_ids: [ids[0]] });

  await page.goto(`/classes/${classId}`);
  await expect(studentRow(page, "Wanjiku")).toBeVisible();
  await page.getByRole("button", { name: "Add students" }).click();
  await expect(page.getByRole("button", { name: "Close" })).toBeVisible();
  await page.getByRole("button", { name: /^Remove / }).click();
  await expect(page.getByRole("button", { name: "Yes, remove" })).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, "/classes/[id] scrolls sideways").toBe(0);
});
