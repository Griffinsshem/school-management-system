import { expect, test, type Page } from "@playwright/test";

import {
  ADMIN_PASSWORD,
  PRINCIPAL_EMAIL,
  SCHOOL_A,
  errorMessage,
  invite,
  logIn,
  logInToSchoolA,
  uniqueEmail,
} from "./helpers";

async function openPeople(page: Page) {
  await page.getByRole("link", { name: "People" }).click();
  await expect(page).toHaveURL("/people");
  await expect(page.getByRole("heading", { level: 2, name: "Members" })).toBeVisible();
}

// Next.js keeps recently visited pages hidden in the tab, so fields are found
// by role (which skips hidden elements) and rows within their own table.
function memberRow(page: Page, text: string) {
  return page.getByRole("region", { name: "Members" }).getByRole("row").filter({ hasText: text });
}

function invitationRow(page: Page, text: string) {
  return page
    .getByRole("region", { name: "Invitations" })
    .getByRole("row")
    .filter({ hasText: text });
}

function emailField(page: Page) {
  return page.getByRole("textbox", { name: "Email address" });
}

test("an administrator invites someone and gets the link once", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await logInToSchoolA(page);
  await openPeople(page);
  const email = uniqueEmail("invited.registrar");

  await emailField(page).fill(email);
  await page.getByRole("combobox", { name: "Role" }).selectOption({ label: "Registrar" });
  await page.getByRole("button", { name: "Create invitation link" }).click();

  const heading = page.getByRole("heading", { name: `Invitation link for ${email} (Registrar)` });
  await expect(heading).toBeVisible();
  await expect(heading).toBeFocused();
  const link = await page.getByRole("textbox", { name: "Invitation link" }).inputValue();
  expect(link).toMatch(/^http:\/\/127\.0\.0\.1:3100\/invitations\/accept#token=[\w-]{20,}$/);
  await expect(invitationRow(page, email)).toContainText("Waiting");

  await page.getByRole("button", { name: "Copy link" }).click();
  await expect(page.getByText("Link copied.")).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(link);

  // The link is shown only once: after "Done" or a reload it is gone.
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByRole("textbox", { name: "Invitation link" })).toHaveCount(0);
  await page.reload();
  await expect(invitationRow(page, email)).toContainText("Waiting");
  expect(await page.content()).not.toContain(link.split("#token=")[1]);

  // The link works for the invitee.
  const invitee = await (await page.context().browser()!.newContext()).newPage();
  await invitee.goto(link);
  await expect(invitee.getByRole("heading", { name: "Create your account" })).toBeVisible();
});

test("mistakes in the invite form are explained", async ({ page }) => {
  await logInToSchoolA(page);
  await openPeople(page);

  await emailField(page).fill("not-an-email");
  await page.getByRole("button", { name: "Create invitation link" }).click();
  await expect(errorMessage(page)).toHaveText("Enter a valid email address.");

  await emailField(page).fill(PRINCIPAL_EMAIL);
  await page.getByRole("combobox", { name: "Role" }).selectOption({ label: "Principal" });
  await page.getByRole("button", { name: "Create invitation link" }).click();
  await expect(errorMessage(page)).toContainText("That person already has this role in the school.");
});

test("an administrator withdraws an invitation", async ({ page }) => {
  await logInToSchoolA(page);
  const email = uniqueEmail("withdrawn");
  const link = await invite(page, email, "teacher");
  await openPeople(page);

  await page.getByRole("button", { name: `Withdraw invitation for ${email}` }).click();
  await expect(page.getByRole("button", { name: "Yes, withdraw" })).toBeFocused();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(invitationRow(page, email)).toContainText("Waiting");

  await page.getByRole("button", { name: `Withdraw invitation for ${email}` }).click();
  await page.getByRole("button", { name: "Yes, withdraw" }).click();
  await expect(page.getByRole("status").filter({ hasText: "was withdrawn" })).toBeVisible();
  await expect(invitationRow(page, email)).toContainText("Withdrawn");
  await expect(page.getByRole("button", { name: `Withdraw invitation for ${email}` })).toHaveCount(0);

  const invitee = await (await page.context().browser()!.newContext()).newPage();
  await invitee.goto(link);
  await expect(invitee.getByRole("heading", { name: "This link is not valid" })).toBeVisible();
});

test("an administrator removes a member, but never the last administrator", async ({ page, browser }) => {
  await logInToSchoolA(page);
  const email = uniqueEmail("leaving.teacher");
  const link = await invite(page, email, "teacher");
  const joiner = await (await browser.newContext()).newPage();
  await joiner.goto(link);
  await joiner.getByLabel("Full name").fill("Leaving Teacher");
  await joiner.getByLabel("Password", { exact: true }).fill(ADMIN_PASSWORD + " x");
  await joiner.getByLabel("Type the password again").fill(ADMIN_PASSWORD + " x");
  await joiner.getByRole("button", { name: "Create account and join" }).click();
  await expect(joiner).toHaveURL("/");
  await openPeople(page);

  await page.getByRole("button", { name: "Remove Leaving Teacher as Teacher" }).click();
  await page.getByRole("button", { name: "Yes, remove" }).click();
  await expect(page.getByRole("status").filter({ hasText: "no longer has the Teacher role" })).toBeVisible();
  await expect(memberRow(page, email)).toContainText("Removed");

  // The removed teacher loses the school at their next request.
  await joiner.reload();
  await expect(joiner.getByText("You are not a member of any school yet.")).toBeVisible();

  // The only school administrator cannot remove themselves.
  await page.getByRole("button", { name: "Remove E2E Admin as School administrator" }).click();
  await expect(page.getByText("Remove your own School administrator role?")).toBeVisible();
  await page.getByRole("button", { name: "Yes, remove" }).click();
  await expect(errorMessage(page)).toContainText("A school must keep at least one school admin.");
  await expect(memberRow(page, "e2e.admin@example.com")).toContainText("Active");
});

test("a principal sees people but cannot change them", async ({ page }) => {
  await page.goto("/login");
  await logIn(page, PRINCIPAL_EMAIL);
  await expect(page.getByRole("heading", { level: 1, name: SCHOOL_A })).toBeVisible();
  await openPeople(page);

  await expect(memberRow(page, PRINCIPAL_EMAIL)).toContainText("Principal");
  await expect(page.getByRole("heading", { name: "Invite someone" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Remove / })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Withdraw / })).toHaveCount(0);

  // Hiding the buttons is a convenience: the API refuses anyway.
  const status = await page.evaluate(async () => {
    const response = await fetch("/api/v1/school/invitations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: "sneaky@example.com", role: "school_admin" }),
    });
    return response.status;
  });
  expect(status).toBe(403);
});

test("people without access are told so", async ({ page }) => {
  await logInToSchoolA(page);
  await page.getByLabel("Switch school").selectOption({ label: "E2E School B" });
  await page.getByRole("button", { name: "Switch" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "E2E School B" })).toBeVisible();
  await expect(page.getByRole("link", { name: "People" })).toHaveCount(0);

  await page.goto("/people");
  await expect(page.getByText("You do not have access to this page in E2E School B.")).toBeVisible();
});
