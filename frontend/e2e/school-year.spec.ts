import { expect, test, type Page } from "@playwright/test";

import { PRINCIPAL_EMAIL, SCHOOL_A, SCHOOL_B, errorMessage, logIn, logInToSchoolA } from "./helpers";

// Today's date in Kenya, as the API works it out, moved by `days`.
function kenyaDate(days = 0): string {
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(new Date());
  const date = new Date(`${today}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

async function openSchoolYear(page: Page) {
  await page.getByRole("link", { name: "School year" }).click();
  await expect(page).toHaveURL("/school-year");
  await expect(page.getByRole("heading", { name: "Today" })).toBeVisible();
}

function today(page: Page) {
  return page.getByRole("region", { name: "Today" });
}

function notice(page: Page) {
  return page.getByRole("main").getByRole("status");
}

async function createYear(page: Page, body: object): Promise<number> {
  return page.evaluate(async (body) => {
    const response = await fetch("/api/v1/school/academic-years", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return response.status;
  }, body);
}

test("a logged-out visitor is sent to the login page", async ({ page }) => {
  await page.goto("/school-year");

  // Sent by the server before the page loads (src/proxy.ts), so no "&expired=1".
  await expect(page).toHaveURL("/login?next=%2Fschool-year");
});

test("an administrator sets up the current school year and its terms", async ({ page }) => {
  await logInToSchoolA(page);
  await openSchoolYear(page);

  await page.getByRole("button", { name: "Add a school year" }).click();
  await expect(page.getByRole("heading", { name: "Add a school year" })).toBeFocused();
  await page.getByLabel("Name").fill("E2E current");
  await page.getByLabel("Starts on", { exact: true }).fill(kenyaDate(-30));
  await page.getByLabel("Ends on", { exact: true }).fill(kenyaDate(300));
  await page.getByLabel("Term 1 starts on").fill(kenyaDate(-30));
  // Only one date of a term: explained before anything is sent.
  await page.getByRole("button", { name: "Add school year" }).click();
  await expect(errorMessage(page)).toHaveText("Enter both dates of Term 1, or leave both empty.");
  await page.getByLabel("Term 1 ends on").fill(kenyaDate(30));
  await page.getByRole("button", { name: "Add school year" }).click();

  await expect(notice(page)).toHaveText("Added the school year E2E current.");
  await expect(today(page)).toContainText("is in Term 1 of E2E current.");
  const year = page.getByRole("region", { name: /^E2E current/ });
  await expect(year.getByRole("row", { name: /Term 1/ })).toContainText("Now");
  await expect(year.getByRole("row", { name: /Term 2/ })).toContainText("Not set");

  // End Term 1 yesterday and set Term 2 to start in ten days: a holiday.
  await page.getByRole("button", { name: "Change the dates of Term 1 of E2E current" }).click();
  await page.getByLabel("Ends on").fill(kenyaDate(-1));
  await page.getByRole("button", { name: "Save term" }).click();
  await expect(notice(page)).toHaveText("Saved the dates of Term 1 of E2E current.");
  await page.getByRole("button", { name: "Set the dates of Term 2 of E2E current" }).click();
  await page.getByLabel("Starts on").fill(kenyaDate(10));
  await page.getByLabel("Ends on").fill(kenyaDate(100));
  await page.getByRole("button", { name: "Save term" }).click();
  await expect(today(page)).toContainText("is a school holiday. Term 2 of E2E current starts on");

  // Mistakes are explained in plain words.
  await page.getByRole("button", { name: "Set the dates of Term 3 of E2E current" }).click();
  await page.getByLabel("Starts on").fill(kenyaDate(50));
  await page.getByLabel("Ends on").fill(kenyaDate(120));
  await page.getByRole("button", { name: "Save term" }).click();
  await expect(errorMessage(page)).toHaveText("Term 3 must start after Term 2 ends.");
  await page.getByLabel("Ends on").fill(kenyaDate(400));
  await page.getByLabel("Starts on").fill(kenyaDate(110));
  await page.getByRole("button", { name: "Save term" }).click();
  await expect(errorMessage(page)).toHaveText("Term 3 must be inside the school year.");
  await page.getByRole("button", { name: "Cancel" }).click();

  await page.getByRole("button", { name: "Add a school year" }).click();
  await page.getByLabel("Name").fill("E2E overlap");
  await page.getByLabel("Starts on", { exact: true }).fill(kenyaDate(300));
  await page.getByLabel("Ends on", { exact: true }).fill(kenyaDate(500));
  await page.getByRole("button", { name: "Add school year" }).click();
  await expect(errorMessage(page)).toHaveText("These dates overlap the school year E2E current.");
  await page.getByRole("button", { name: "Cancel" }).click();

  await page.getByRole("button", { name: "Edit the school year E2E current" }).click();
  await page.getByLabel("Name").fill("E2E this year");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(notice(page)).toHaveText("Saved changes to the school year E2E this year.");
  await expect(page.getByRole("heading", { level: 2, name: /^E2E this year/ })).toBeVisible();
});

test("a principal sees the school year but cannot change it", async ({ page }) => {
  await page.goto("/login");
  await logIn(page, PRINCIPAL_EMAIL);
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL_A })).toBeVisible();
  await expect(page.getByText("See the school year and terms")).toBeVisible();
  await openSchoolYear(page);

  await expect(page.getByRole("button", { name: "Add a school year" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Edit the school year/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /dates of Term/ })).toHaveCount(0);

  // Hiding the buttons is a convenience: the API refuses anyway.
  expect(await createYear(page, { name: "Sneaky", starts_on: "2091-01-01", ends_on: "2091-11-30" })).toBe(
    403,
  );
});

test("a teacher sees the school year page of their school", async ({ page }) => {
  await logInToSchoolA(page);
  await page.getByLabel("Switch school").selectOption({ label: SCHOOL_B });
  await page.getByRole("button", { name: "Switch" }).click();
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL_B })).toBeVisible();
  await openSchoolYear(page);

  // School A's years belong to School A only.
  await expect(today(page).getByText("No school years yet.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Add a school year" })).toHaveCount(0);
});

test("the school year page fits a phone screen without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await logInToSchoolA(page);
  const status = await createYear(page, {
    name: "E2E phone 2095",
    starts_on: "2095-01-03",
    ends_on: "2095-11-25",
    terms: [{ number: 1, starts_on: "2095-01-03", ends_on: "2095-04-01" }],
  });
  expect(status).toBe(201);

  await page.goto("/school-year");
  await expect(page.getByRole("heading", { name: /^E2E phone 2095/ })).toBeVisible();
  await page.getByRole("button", { name: "Add a school year" }).click();
  await expect(page.getByLabel("Term 3 ends on")).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, "/school-year scrolls sideways").toBe(0);
});
