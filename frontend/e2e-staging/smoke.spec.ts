import { expect, test, type Page } from "@playwright/test";

// The demo accounts and data created by backend/scripts/seed_staging.py.
const ADMIN_EMAIL = "staging.admin@example.com";
const TEACHER_EMAIL = "staging.teacher@example.com";
const SCHOOL_A = "Staging Demo School A";
const PASSWORD = process.env.STAGING_PASSWORD ?? "";

test.beforeAll(async ({ playwright, baseURL }) => {
  // Wake the free API (and its database) before the first real check.
  const api = await playwright.request.newContext({ baseURL });
  await expect
    .poll(async () => (await api.get("/api/v1/health/ready", { timeout: 90_000 })).status(), {
      timeout: 110_000,
    })
    .toBe(200);
  await api.dispose();
});

async function logIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
}

async function logOut(page: Page) {
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL("/login");
}

function role(page: Page) {
  return page.locator("dt:has-text('Your role') + dd");
}

test("a logged-out visitor is sent to the login page", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveURL("/login?next=%2F");
});

test("an administrator sees the school's students and staff", async ({ page, context }) => {
  await logIn(page, ADMIN_EMAIL);
  await expect(page.getByRole("heading", { name: "Choose a school" })).toBeVisible();
  await page.getByRole("button", { name: new RegExp(SCHOOL_A) }).click();
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL_A })).toBeVisible();
  await expect(role(page)).toContainText("School administrator");

  // Production cookie: __Host- prefix, Secure, HttpOnly, SameSite=Lax.
  const cookies = await context.cookies();
  expect(cookies.map((c) => [c.name, c.secure, c.httpOnly, c.sameSite])).toEqual([
    ["__Host-sms_session", true, true, "Lax"],
  ]);

  await page.getByRole("link", { name: "Students" }).click();
  await expect(page.getByRole("status")).toHaveText("Showing 1 to 12 of 12 students.");
  await page.getByRole("searchbox").fill("Amani");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText('Showing 1 to 1 of 1 student matching "Amani".');
  await expect(page.getByRole("table")).toContainText("Amani Demo");

  await page.getByRole("link", { name: "People" }).click();
  const members = page.getByRole("region", { name: "Members" });
  for (const name of ["Admin Demo", "Principal Demo", "Teacher Demo"]) {
    await expect(members).toContainText(name);
  }

  await logOut(page);
  expect(await context.cookies()).toEqual([]);
  await page.goto("/students");
  await expect(page).toHaveURL(/\/login/);
});

test("a teacher sees the school year but no student or staff pages yet", async ({ page }) => {
  await logIn(page, TEACHER_EMAIL);
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL_A })).toBeVisible();
  await expect(role(page)).toHaveText("Teacher");
  await expect(page.getByRole("link", { name: "Students" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "People" })).toHaveCount(0);

  await page.getByRole("link", { name: "School year" }).click();
  await expect(page.getByRole("heading", { name: "Today" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add a school year" })).toHaveCount(0);

  await logOut(page);
});
