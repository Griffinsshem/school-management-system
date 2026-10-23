import { expect, test, type Page } from "@playwright/test";

import { PRINCIPAL_EMAIL, SCHOOL_A, errorMessage, logIn, logInToSchoolA } from "./helpers";

// Clearly fake students, created in the test database only. Each test uses
// its own prefix so tests do not depend on each other's data.
function prefix(): string {
  return `T${Date.now().toString(36).toUpperCase()}`;
}

async function openStudents(page: Page) {
  await page.getByRole("link", { name: "Students" }).click();
  await expect(page).toHaveURL("/students");
  await expect(page.getByRole("status").filter({ hasText: /Showing|No students/ })).toBeVisible();
}

async function addStudents(page: Page, start: string, count: number) {
  const statuses = await page.evaluate(
    async ([start, count]) => {
      const results: number[] = [];
      for (let i = 1; i <= Number(count); i++) {
        const number = String(i).padStart(3, "0");
        const response = await fetch("/api/v1/school/students", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ admission_number: `${start}-${number}`, full_name: `${start} Pupil ${number}` }),
        });
        results.push(response.status);
      }
      return results;
    },
    [start, String(count)],
  );
  expect(statuses.every((status) => status === 201)).toBe(true);
}

async function search(page: Page, text: string) {
  await page.getByRole("searchbox").fill(text);
  await page.getByRole("button", { name: "Search", exact: true }).click();
}

function row(page: Page, text: string) {
  return page.getByRole("table").getByRole("row").filter({ hasText: text });
}

test("students are listed in pages and searched without the search in the address", async ({
  page,
}) => {
  await logInToSchoolA(page);
  const start = prefix();
  await addStudents(page, start, 55);
  await openStudents(page);

  await search(page, start);
  await expect(page.getByRole("status")).toHaveText(
    `Showing 1 to 50 of 55 students matching "${start}".`,
  );
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(51);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Page 2 of 2")).toBeVisible();
  await expect(page.getByRole("status")).toHaveText(
    `Showing 51 to 55 of 55 students matching "${start}".`,
  );

  await search(page, `${start}-007`);
  await expect(page.getByRole("status")).toHaveText(
    `Showing 1 to 1 of 1 student matching "${start}-007".`,
  );
  await search(page, `${start}-none`);
  await expect(page.getByRole("status")).toHaveText(`No students match "${start}-none".`);
  // Children's names never go into the page's own address (browser history).
  expect(page.url()).toBe("http://127.0.0.1:3100/students");

  await page.getByRole("button", { name: "Clear" }).click();
  await expect(page.getByRole("status")).toContainText("Showing 1 to 50 of");
});

test("an administrator adds a student, and mistakes are explained", async ({ page }) => {
  await logInToSchoolA(page);
  await openStudents(page);
  const start = prefix();

  await page.getByRole("button", { name: "Add a student" }).click();
  await expect(page.getByRole("heading", { name: "Add a student" })).toBeFocused();
  await page.getByLabel("Admission number", { exact: true }).fill(`${start}-1`);
  await page.getByLabel("Full name").fill("Amani Test Pupil");
  await page.getByLabel(/Date of birth/).fill("2016-02-29");
  await page.getByRole("button", { name: "Add student" }).click();

  await expect(page.getByRole("status").filter({ hasText: "Added" })).toHaveText(
    `Added Amani Test Pupil (${start}-1).`,
  );
  await search(page, start);
  await expect(row(page, `${start}-1`)).toContainText("Amani Test Pupil");
  // A calendar date: shown as stored, never shifted by time zones.
  await expect(row(page, `${start}-1`)).toContainText(/Feb 29, 2016|29 Feb 2016/);

  // The same admission number again.
  await page.getByRole("button", { name: "Add a student" }).click();
  await page.getByLabel("Admission number", { exact: true }).fill(`${start}-1`);
  await page.getByLabel("Full name").fill("Someone Else");
  await page.getByRole("button", { name: "Add student" }).click();
  await expect(errorMessage(page)).toContainText(
    "Another student in this school has that admission number.",
  );

  // A date of birth in the future.
  await page.getByLabel("Admission number", { exact: true }).fill(`${start}-2`);
  await page.getByLabel(/Date of birth/).fill("2099-01-01");
  await page.getByRole("button", { name: "Add student" }).click();
  await expect(errorMessage(page)).toHaveText("Date of birth cannot be in the future.");

  // A date of birth more than 30 years ago.
  await page.getByLabel(/Date of birth/).fill("1990-01-01");
  await page.getByRole("button", { name: "Add student" }).click();
  await expect(errorMessage(page)).toHaveText("Date of birth cannot be more than 30 years ago.");

  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByRole("heading", { name: "Add a student" })).toHaveCount(0);
});

test("an administrator edits and deactivates a student", async ({ page }) => {
  await logInToSchoolA(page);
  const start = prefix();
  await addStudents(page, start, 1);
  await openStudents(page);
  await search(page, start);

  await page.getByRole("button", { name: `Edit ${start} Pupil 001 (${start}-001)` }).click();
  await page.getByLabel("Full name").fill("Renamed Test Pupil");
  await page.getByLabel(/Date of birth/).fill("2014-07-15");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved" })).toHaveText(
    `Saved changes to Renamed Test Pupil (${start}-001).`,
  );
  await expect(row(page, `${start}-001`)).toContainText("Renamed Test Pupil");

  // Clearing the date of birth removes it.
  await page.getByRole("button", { name: `Edit Renamed Test Pupil (${start}-001)` }).click();
  await page.getByLabel(/Date of birth/).fill("");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Saved" })).toBeVisible();
  await expect(row(page, `${start}-001`).getByRole("cell").nth(2)).toHaveText("-");

  const deactivate = page.getByRole("button", {
    name: `Deactivate Renamed Test Pupil (${start}-001)`,
  });
  await deactivate.click();
  await expect(page.getByRole("button", { name: "Yes, deactivate" })).toBeFocused();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(row(page, `${start}-001`)).toContainText("Active");

  await deactivate.click();
  await page.getByRole("button", { name: "Yes, deactivate" }).click();
  await expect(page.getByRole("status").filter({ hasText: "inactive" })).toHaveText(
    `Renamed Test Pupil (${start}-001) is now inactive.`,
  );
  await expect(row(page, `${start}-001`)).toContainText("Inactive");
  await expect(deactivate).toHaveCount(0);
});

test("a principal sees students but cannot change them", async ({ page }) => {
  await page.goto("/login");
  await logIn(page, PRINCIPAL_EMAIL);
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL_A })).toBeVisible();
  await openStudents(page);

  await expect(page.getByRole("button", { name: "Add a student" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Edit / })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Deactivate / })).toHaveCount(0);

  // Hiding the buttons is a convenience: the API refuses anyway.
  const status = await page.evaluate(async () => {
    const response = await fetch("/api/v1/school/students", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ admission_number: "SNEAKY-1", full_name: "Not Allowed" }),
    });
    return response.status;
  });
  expect(status).toBe(403);
});

test("a teacher has no access to students", async ({ page }) => {
  await logInToSchoolA(page);
  await page.getByLabel("Switch school").selectOption({ label: "E2E School B" });
  await page.getByRole("button", { name: "Switch" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "E2E School B" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Students" })).toHaveCount(0);

  await page.goto("/students");
  await expect(page.getByText("You do not have access to this page in E2E School B.")).toBeVisible();
});

test("logged-in pages fit a phone screen without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await logInToSchoolA(page);
  const pages: [string, RegExp][] = [
    ["/", /Your role/],
    ["/students", /Showing|No students/],
    ["/people", /Invitations/],
  ];
  for (const [path, loaded] of pages) {
    await page.goto(path);
    // Wait until the page's own content (tables included) has loaded.
    await expect(page.getByRole("main").getByText(loaded).first()).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `${path} scrolls sideways`).toBe(0);
  }
});
