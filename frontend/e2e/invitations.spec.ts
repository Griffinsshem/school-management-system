import { expect, test, type Page } from "@playwright/test";

import { SCHOOL_A, errorMessage, invite, logIn, logInToSchoolA, uniqueEmail } from "./helpers";

// Fake people created during the tests, in the test database only.
const PASSWORD = "a long enough password";

async function createAccount(page: Page, fullName: string, password: string) {
  await page.getByLabel("Full name").fill(fullName);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Type the password again").fill(password);
  await page.getByRole("button", { name: "Create account and join" }).click();
}

test("a new person accepts an invitation and creates an account", async ({ page, browser }) => {
  await logInToSchoolA(page);
  const email = uniqueEmail("new.teacher");
  const link = await invite(page, email, "teacher");

  // The invitee uses a separate, logged-out browser.
  const invitee = await browser.newContext();
  const guest = await invitee.newPage();
  const requested: string[] = [];
  guest.on("request", (request) => requested.push(request.url()));
  await guest.goto(link);

  await expect(guest.getByRole("heading", { name: "Create your account" })).toBeVisible();
  await expect(guest.getByText(`${SCHOOL_A} has invited ${email} to join as Teacher.`)).toBeVisible();
  // The token is removed from the address bar and never sent in a URL.
  expect(guest.url()).toBe("http://127.0.0.1:3100/invitations/accept");
  const token = link.split("#token=")[1];
  expect(requested.some((url) => url.includes(token))).toBe(false);

  // A reload still works: the token is kept in this tab's session storage.
  await guest.reload();
  await expect(guest.getByRole("heading", { name: "Create your account" })).toBeVisible();

  await guest.getByLabel("Full name").fill("New Teacher");
  await guest.getByLabel("Password", { exact: true }).fill("too short");
  await guest.getByLabel("Type the password again").fill("too short");
  await guest.getByRole("button", { name: "Create account and join" }).click();
  await expect(errorMessage(guest)).toHaveText("Choose a password of 12 to 128 characters.");

  await guest.getByLabel("Password", { exact: true }).fill("a long enough password");
  await guest.getByLabel("Type the password again").fill("a different password");
  await guest.getByRole("button", { name: "Create account and join" }).click();
  await expect(errorMessage(guest)).toHaveText("The two passwords do not match.");

  await guest.getByLabel("Type the password again").fill("a long enough password");
  await guest.getByRole("button", { name: "Create account and join" }).click();

  await expect(guest).toHaveURL("/");
  await expect(guest.getByRole("heading", { level: 1, name: SCHOOL_A })).toBeVisible();
  await expect(guest.locator("dt:has-text('Your role') + dd")).toHaveText("Teacher");
  expect(await guest.evaluate(() => sessionStorage.getItem("sms.invitation_token"))).toBeNull();

  // The link works only once.
  const again = await invitee.newPage();
  await again.goto(link);
  await expect(again.getByRole("heading", { name: "This link is not valid" })).toBeVisible();
  await invitee.close();
});

test("an existing account logs in to accept, after the wrong account logs out", async ({
  page,
  browser,
}) => {
  await logInToSchoolA(page);
  const parentEmail = uniqueEmail("teacher.and.parent");
  const otherEmail = uniqueEmail("other.teacher");

  // Two people already have accounts: each joined as a teacher.
  for (const email of [parentEmail, otherEmail]) {
    const context = await browser.newContext();
    const tab = await context.newPage();
    await tab.goto(await invite(page, email, "teacher"));
    await createAccount(tab, "Demo Teacher", PASSWORD);
    await expect(tab).toHaveURL("/");
    await context.close();
  }
  // The first teacher is now invited as a parent too.
  const guardianLink = await invite(page, parentEmail, "guardian");

  // On a shared computer, the other teacher is still logged in.
  const shared = await browser.newContext();
  const tab = await shared.newPage();
  await tab.goto("/login");
  await logIn(tab, otherEmail, PASSWORD);
  await expect(tab.getByRole("heading", { level: 1, name: SCHOOL_A })).toBeVisible();

  await tab.goto(guardianLink);
  await expect(tab.getByText(`You are logged in as ${otherEmail}`)).toBeVisible();
  await tab.getByRole("button", { name: "Log out" }).click();

  await expect(tab.getByText("This email address already has an account.")).toBeVisible();
  await tab.getByRole("link", { name: "Log in" }).click();
  await expect(tab).toHaveURL("/login?next=%2Finvitations%2Faccept");
  await logIn(tab, parentEmail, PASSWORD);

  await expect(tab).toHaveURL("/invitations/accept");
  await tab.getByRole("button", { name: "Accept invitation" }).click();
  await expect(tab).toHaveURL("/");
  const roles = tab.locator("dt:has-text('Your role') + dd");
  await expect(roles).toContainText("Teacher");
  await expect(roles).toContainText("Parent or guardian");
  await shared.close();
});

test("a made-up link is explained, not accepted", async ({ page }) => {
  await page.goto("/invitations/accept#token=made-up-token");

  await expect(page.getByRole("heading", { name: "This link is not valid" })).toBeVisible();
  expect(page.url()).toBe("http://127.0.0.1:3100/invitations/accept");
});
