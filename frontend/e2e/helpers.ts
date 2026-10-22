import { expect, type Page } from "@playwright/test";

// The fake administrator created by backend/scripts/e2e_server.py in the test
// database. Keep in sync with that script.
export const ADMIN_EMAIL = "e2e.admin@example.com";
export const ADMIN_PASSWORD = "e2e only password";
export const SCHOOL_A = "E2E School A";
export const SCHOOL_B = "E2E School B";

// Next.js has its own (empty) role="alert" element for page announcements,
// so error messages are looked up inside the page's main content.
export function errorMessage(page: Page) {
  return page.locator("main [role=alert]");
}

export async function logIn(page: Page, email = ADMIN_EMAIL, password = ADMIN_PASSWORD) {
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
}

// Logs in as the administrator and makes E2E School A the active school.
export async function logInToSchoolA(page: Page) {
  await page.goto("/login");
  await logIn(page);
  await expect(page.getByRole("heading", { name: "Choose a school" })).toBeVisible();
  await page.getByRole("button", { name: new RegExp(SCHOOL_A) }).click();
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL_A })).toBeVisible();
}

// Creates an invitation through the API from the administrator's logged-in
// page (as a future "invite" screen will) and returns the link.
export async function invite(page: Page, email: string, role: string): Promise<string> {
  const body = await page.evaluate(
    async ([email, role]) => {
      const response = await fetch("/api/v1/school/invitations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, role }),
      });
      return { status: response.status, json: await response.json() };
    },
    [email, role],
  );
  expect(body.status).toBe(201);
  return body.json.accept_url as string;
}

export function uniqueEmail(prefix: string): string {
  return `${prefix}.${Date.now()}.${Math.floor(Math.random() * 1e6)}@example.com`;
}
