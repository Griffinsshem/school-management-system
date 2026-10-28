import { expect, test, type Page } from "@playwright/test";

import { PRINCIPAL_EMAIL, SCHOOL_A, TEACHER_EMAIL, errorMessage, logIn, logInToSchoolA } from "./helpers";

// Clearly fake guardians in E2E School A. Each test makes its own students
// and phone numbers (in the 0700 range), so tests do not depend on each other.

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

function unique(): string {
  return `G${Date.now().toString(36).slice(-6).toUpperCase()}`;
}

// A made-up number such as "0700 123 456", different for each call.
let counter = 0;
function phone(): string {
  counter += 1;
  const digits = String((Date.now() * 10 + counter) % 1_000_000).padStart(6, "0");
  return `0700 ${digits.slice(0, 3)} ${digits.slice(3)}`;
}

async function newStudent(page: Page, name: string): Promise<string> {
  counter += 1;
  const created = await call(page, "POST", "/school/students", {
    admission_number: `G-${Date.now().toString(36)}-${counter}`,
    full_name: name,
  });
  expect(created.status).toBe(201);
  return (created.json.student as { id: string }).id;
}

function guardian(page: Page, name: string) {
  return page.getByRole("listitem", { name });
}

function notice(page: Page) {
  return page.getByRole("main").getByRole("status").filter({ hasText: /^(Added|Removed|Saved|.* is now)/ });
}

async function addNew(page: Page, number: string, name: string, relationship: string, primary = false) {
  await page.getByRole("button", { name: "Add a guardian" }).click();
  await page.getByLabel("Mobile number").fill(number);
  await page.getByRole("button", { name: "Find" }).click();
  await expect(page.getByText(/^No guardian has the number/)).toBeVisible();
  await page.getByLabel("Full name").fill(name);
  await page.getByLabel("Relationship to the student").selectOption({ label: relationship });
  if (primary) {
    await page.getByLabel("Make this the primary contact").check();
  }
  await page.getByRole("button", { name: "Add guardian" }).click();
}

test("a logged-out visitor is sent to the login page", async ({ page }) => {
  await page.goto("/students/00000000-0000-0000-0000-000000000000");

  await expect(page).toHaveURL("/login?next=%2Fstudents%2F00000000-0000-0000-0000-000000000000");
});

test("an administrator adds guardians, and a sibling's parent is linked, not added twice", async ({ page }) => {
  await logInToSchoolA(page);
  const name = unique();
  const amani = await newStudent(page, `Amani ${name}`);
  const baraka = await newStudent(page, `Baraka ${name}`);
  const mother = phone();

  await page.goto(`/students/${amani}`);
  await expect(page.getByRole("heading", { level: 1, name: `Amani ${name}` })).toBeVisible();
  await expect(page.getByText("No guardians recorded yet.")).toBeVisible();

  // A wrong number is explained.
  await page.getByRole("button", { name: "Add a guardian" }).click();
  await page.getByLabel("Mobile number").fill("0812 000 000");
  await page.getByRole("button", { name: "Find" }).click();
  await expect(errorMessage(page)).toHaveText("Enter a Kenyan mobile number, such as 0712 345 678.");
  await page.getByRole("button", { name: "Cancel" }).click();

  // The first guardian becomes the primary contact; a relationship is required.
  await page.getByRole("button", { name: "Add a guardian" }).click();
  await page.getByLabel("Mobile number").fill(mother);
  await page.getByRole("button", { name: "Find" }).click();
  await page.getByLabel("Full name").fill(`Wanjiru ${name}`);
  await page.getByRole("button", { name: "Add guardian" }).click();
  await expect(errorMessage(page)).toHaveText("Choose the relationship to the student.");
  await page.getByLabel("Relationship to the student").selectOption({ label: "Mother" });
  await page.getByRole("button", { name: "Add guardian" }).click();
  await expect(notice(page)).toHaveText(`Added Wanjiru ${name} as a guardian of Amani ${name}.`);
  await expect(guardian(page, `Wanjiru ${name}`)).toContainText("Primary contact");
  await expect(guardian(page, `Wanjiru ${name}`)).toContainText(mother);

  // A second guardian, made primary instead.
  await addNew(page, phone(), `Otieno ${name}`, "Father", true);
  await expect(guardian(page, `Otieno ${name}`)).toContainText("Primary contact");
  await expect(guardian(page, `Wanjiru ${name}`)).not.toContainText("Primary contact");

  // The sibling: the same number, written differently, finds the same person.
  await page.goto(`/students/${baraka}`);
  await page.getByRole("button", { name: "Add a guardian" }).click();
  await page.getByLabel("Mobile number").fill(`+254${mother.replace(/\s/g, "").slice(1)}`);
  await page.getByRole("button", { name: "Find" }).click();
  await expect(page.getByText(`is already recorded as a guardian of Amani ${name}.`)).toBeVisible();
  await page.getByLabel("Relationship to the student").selectOption({ label: "Mother" });
  await page.getByRole("button", { name: `Link Wanjiru ${name}` }).click();
  await expect(notice(page)).toHaveText(`Added Wanjiru ${name} as a guardian of Baraka ${name}.`);
  await expect(guardian(page, `Wanjiru ${name}`)).toContainText("Primary contact");

  // One record: a correction shows for both children.
  await page.getByRole("button", { name: `Edit Wanjiru ${name}` }).click();
  await page.getByLabel("Full name").fill(`Wanjiru Kamau ${name}`);
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(notice(page)).toHaveText(`Saved changes to Wanjiru Kamau ${name}.`);
  await page.goto(`/students/${amani}`);
  await expect(guardian(page, `Wanjiru Kamau ${name}`)).toBeVisible();

  // Removing from one child keeps the record for the other.
  await page.getByRole("button", { name: `Remove Wanjiru Kamau ${name}` }).click();
  await page.getByRole("button", { name: "Yes, remove" }).click();
  await expect(notice(page)).toHaveText(`Removed Wanjiru Kamau ${name} from Amani ${name}.`);
  await expect(guardian(page, `Wanjiru Kamau ${name}`)).toHaveCount(0);
  await page.goto(`/students/${baraka}`);
  await expect(guardian(page, `Wanjiru Kamau ${name}`)).toBeVisible();
});

test("students link to their page from the student list", async ({ page }) => {
  await logInToSchoolA(page);
  const name = unique();
  await newStudent(page, `Chausiku ${name}`);

  await page.getByRole("link", { name: "Students" }).click();
  await page.getByRole("searchbox").fill(name);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.getByRole("link", { name: `Chausiku ${name}` }).click();

  await expect(page.getByRole("heading", { level: 1, name: `Chausiku ${name}` })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Guardians" })).toBeVisible();
});

test("a principal sees guardians but cannot change them", async ({ page }) => {
  await logInToSchoolA(page);
  const name = unique();
  const student = await newStudent(page, `Dalila ${name}`);
  const added = await call(page, "POST", `/school/students/${student}/guardians`, {
    full_name: `Akinyi ${name}`,
    phone: phone(),
    relationship: "grandparent",
  });
  expect(added.status).toBe(201);
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL("/login");

  await logIn(page, PRINCIPAL_EMAIL);
  await expect(page.getByText("See students' guardians")).toBeVisible();
  await page.goto(`/students/${student}`);

  await expect(guardian(page, `Akinyi ${name}`)).toContainText("Grandparent");
  await expect(page.getByRole("button", { name: "Add a guardian" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^(Edit|Remove|Make) / })).toHaveCount(0);
});

test("teachers see no student or guardian pages", async ({ page }) => {
  await page.goto("/login");
  await logIn(page, TEACHER_EMAIL);
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL_A })).toBeVisible();
  await expect(page.getByText("See students' guardians")).toHaveCount(0);

  await page.goto("/students/00000000-0000-0000-0000-000000000000");

  await expect(page.getByText("You do not have access to this page in E2E School A.")).toBeVisible();
});

test("the student page fits a phone screen without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await logInToSchoolA(page);
  const name = unique();
  const student = await newStudent(page, `Wanjiku Nyambura Kamau ${name}`);
  await call(page, "POST", `/school/students/${student}/guardians`, {
    full_name: `Mwangi Kariuki Njoroge ${name}`,
    phone: phone(),
    email: "a.very.long.email.address.for.testing@example.com",
    relationship: "other_relative",
  });

  await page.goto(`/students/${student}`);
  await expect(guardian(page, `Mwangi Kariuki Njoroge ${name}`)).toBeVisible();
  await page.getByRole("button", { name: "Add a guardian" }).click();
  await expect(page.getByLabel("Mobile number")).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, "/students/[id] scrolls sideways").toBe(0);
});
