import { expect, test } from "@playwright/test";

import {
  ADMIN_EMAIL,
  ADMIN_PASSWORD,
  SCHOOL_A,
  SCHOOL_B,
  errorMessage,
  logIn,
  logInToSchoolA,
} from "./helpers";

test("a logged-out visitor is sent to the login page", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveURL("/login?next=%2F");
  await expect(page).toHaveTitle("Log in | School Management System");
});

test("a wrong password shows one generic message", async ({ page }) => {
  await page.goto("/login");
  await logIn(page, undefined, "not the right password");

  await expect(errorMessage(page)).toHaveText("Invalid email or password.");
  await expect(errorMessage(page)).toBeFocused();
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");
  await expect(page).toHaveURL(/\/login/);
});

test("logging in, choosing and switching school, and logging out", async ({ page, context }) => {
  await logInToSchoolA(page);
  await expect(page.locator("dt:has-text('Your role') + dd")).toContainText("School administrator");
  await expect(page.getByText("Invite and remove members")).toBeVisible();

  // The session cookie is HttpOnly: page scripts cannot read it.
  const cookies = await context.cookies();
  expect(cookies.map((c) => [c.name, c.httpOnly, c.sameSite])).toEqual([
    ["sms_session", true, "Lax"],
  ]);
  expect(await page.evaluate(() => document.cookie)).toBe("");

  await page.getByLabel("Switch school").selectOption({ label: SCHOOL_B });
  await page.getByRole("button", { name: "Switch" }).click();
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL_B })).toBeVisible();
  await expect(page.locator("dt:has-text('Your role') + dd")).toHaveText("Teacher");
  await expect(page.getByText("Nothing yet.")).toBeVisible();

  // The choice is kept by the server, so it survives a reload.
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL_B })).toBeVisible();

  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL("/login");
  expect(await context.cookies()).toEqual([]);
  await page.goto("/");
  await expect(page).toHaveURL("/login?next=%2F");
});

test("nothing private stays in the tab after login and logout", async ({ page }) => {
  await page.goto("/login");
  await logIn(page);
  await expect(page.getByRole("heading", { name: "Choose a school" })).toBeVisible();
  // Next.js keeps the login page hidden in the tab: its password is cleared.
  const passwords = await page.evaluate(() =>
    [...document.querySelectorAll<HTMLInputElement>("input[type=password]")].map((i) => i.value),
  );
  expect(passwords.every((value) => value === "")).toBe(true);

  await page.getByRole("button", { name: new RegExp(SCHOOL_A) }).click();
  await page.getByRole("link", { name: "People" }).click();
  await expect(page.getByRole("heading", { name: "Members" })).toBeVisible();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL("/login");
  // Logging out loads the login page afresh: the previous pages are gone.
  expect(await page.content()).not.toContain(ADMIN_EMAIL);
});

test("after login, only addresses on this site are followed", async ({ page }) => {
  await page.goto("/login?next=https://evil.example/steal");
  await logIn(page);

  await expect(page).toHaveURL("/");
});

test("an ended session leads back to the login page with a note", async ({ page, context }) => {
  await context.addCookies([
    { name: "sms_session", value: "no-longer-valid", url: "http://127.0.0.1:3100" },
  ]);

  await page.goto("/");

  await expect(page).toHaveURL("/login?next=%2F&expired=1");
  await expect(page.getByRole("status")).toHaveText(
    "Your session has ended. Please log in again.",
  );
});

test("the login form works with the keyboard alone", async ({ page }) => {
  await page.goto("/login");
  // The form appears once the page has loaded in the browser.
  await expect(page.getByLabel("Email address")).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Email address")).toBeFocused();
  await page.keyboard.type(ADMIN_EMAIL);
  await page.keyboard.press("Tab");
  await page.keyboard.type(ADMIN_PASSWORD);
  await page.keyboard.press("Enter");

  await expect(page.getByRole("heading", { name: "Choose a school" })).toBeVisible();
});

test("pages are sent with security headers", async ({ request }) => {
  const response = await request.get("/login");
  const headers = response.headers();

  expect(headers["x-frame-options"]).toBe("DENY");
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["referrer-policy"]).toBe("strict-origin-when-cross-origin");
  expect(headers["x-powered-by"]).toBeUndefined();
  const invitation = await request.get("/invitations/accept");
  expect(invitation.headers()["referrer-policy"]).toBe("no-referrer");
});

test(`the school list shows ${SCHOOL_A} and ${SCHOOL_B}`, async ({ page }) => {
  await page.goto("/login");
  await logIn(page);

  const choices = page.getByRole("main").getByRole("button");
  await expect(choices).toHaveCount(2);
  await expect(choices.nth(0)).toContainText(SCHOOL_A);
  await expect(choices.nth(1)).toContainText(SCHOOL_B);
});
