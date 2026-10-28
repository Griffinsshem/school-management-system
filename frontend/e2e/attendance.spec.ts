import { expect, test, type Page } from "@playwright/test";

import {
  ATTENDANCE_ADMIN_EMAIL,
  ATTENDANCE_TEACHER_EMAIL,
  PRINCIPAL_EMAIL,
  SCHOOL_C,
  errorMessage,
  logIn,
} from "./helpers";

// These tests use E2E School C, which has its own administrator and teacher,
// so its school year around today does not clash with the school-year tests
// in School A. Registers need a term day up to today, and teachers may only
// change the last 7 days, so the dates follow the real calendar in Kenya.

type Json = Record<string, unknown>;

function kenyaDate(days = 0): string {
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(new Date());
  const date = new Date(`${today}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

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

async function logInAs(page: Page, email: string) {
  await page.goto("/login");
  await logIn(page, email);
  await expect(page.getByRole("heading", { level: 1, name: email === PRINCIPAL_EMAIL ? /School A/ : SCHOOL_C })).toBeVisible();
}

// Waits for the login page, so the next navigation does not interrupt it.
async function logOut(page: Page) {
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL("/login");
}

// School C's year around today, created the first time.
async function currentYear(page: Page): Promise<string> {
  const { json } = await call(page, "GET", "/school/academic-years");
  const years = json.academic_years as { id: string; name: string }[];
  const existing = years.find((year) => year.name === "E2E now");
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

// A class of three students taught by the attendance teacher, set up through
// the API by School C's administrator (already logged in).
async function classOfThree(page: Page) {
  const yearId = await currentYear(page);
  const name = `T${Date.now().toString(36).slice(-6).toUpperCase()}`;
  const made = await call(page, "POST", "/school/classes", {
    academic_year_id: yearId,
    grade: "grade_4",
    stream: name,
  });
  expect(made.status).toBe(201);
  const classId = (made.json.class as { id: string }).id;
  const ids: string[] = [];
  for (const [n, first] of ["Amani", "Baraka", "Chausiku"].entries()) {
    const student = await call(page, "POST", "/school/students", {
      admission_number: `${name}-${n + 1}`,
      full_name: `${first} ${name}`,
    });
    expect(student.status).toBe(201);
    ids.push((student.json.student as { id: string }).id);
  }
  expect((await call(page, "POST", `/school/classes/${classId}/students`, { student_ids: ids })).status).toBe(201);
  const { json } = await call(page, "GET", "/school/members");
  const teacher = (json.members as { id: string; role: string; user: { email: string } }[]).find(
    (m) => m.user.email === ATTENDANCE_TEACHER_EMAIL && m.role === "teacher",
  );
  expect((await call(page, "POST", `/school/classes/${classId}/teachers`, { membership_id: teacher?.id })).status).toBe(
    201,
  );
  return { classId, className: `Grade 4 ${name}`, name, ids };
}

function student(page: Page, fullName: string) {
  return page.getByRole("group", { name: new RegExp(`^${fullName}`) });
}

function notice(page: Page) {
  return page.getByRole("main").getByRole("status");
}

test("a logged-out visitor is sent to the login page", async ({ page }) => {
  await page.goto("/attendance");
  await expect(page).toHaveURL("/login?next=%2Fattendance");

  // The register keeps its day, so the visitor comes back to it.
  await page.goto("/classes/00000000-0000-0000-0000-000000000000/attendance?date=2027-02-10");
  await expect(page).toHaveURL(
    "/login?next=%2Fclasses%2F00000000-0000-0000-0000-000000000000%2Fattendance%3Fdate%3D2027-02-10",
  );
  await page.goto("/classes/00000000-0000-0000-0000-000000000000/attendance/summary");
  await expect(page).toHaveURL(
    "/login?next=%2Fclasses%2F00000000-0000-0000-0000-000000000000%2Fattendance%2Fsummary",
  );
});

test("a teacher takes today's register and corrects it", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const { className, name } = await classOfThree(page);
  await logOut(page);

  await logInAs(page, ATTENDANCE_TEACHER_EMAIL);
  await expect(page.getByText("Take attendance for the classes you teach")).toBeVisible();
  await page.getByRole("link", { name: "Attendance" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Attendance" })).toBeVisible();
  const row = page.getByRole("row", { name: new RegExp(`^${className}`) });
  await expect(row).toContainText("Not taken");
  await row.getByRole("link", { name: className }).click();

  await expect(page.getByRole("heading", { level: 1, name: `${className} register` })).toBeVisible();
  await expect(page.getByText("Not taken yet. Everyone starts as present")).toBeVisible();
  await expect(page.getByText("Present 3, absent 0, late 0")).toBeVisible();

  // An absence needs a reason from the list.
  await student(page, `Baraka ${name}`).getByLabel("Absent").check();
  await student(page, `Chausiku ${name}`).getByLabel("Late").check();
  await page.getByRole("button", { name: "Save register" }).click();
  await expect(errorMessage(page)).toHaveText(`Choose a reason for each absence: Baraka ${name}.`);
  await student(page, `Baraka ${name}`).getByLabel("Reason").selectOption({ label: "Sick" });
  await expect(page.getByText("Present 1, absent 1, late 1")).toBeVisible();
  await page.getByRole("button", { name: "Save register" }).click();

  await expect(notice(page)).toHaveText("Register saved.");
  await expect(page.getByText(/^Taken by E2E Attendance Teacher on /)).toBeVisible();
  await expect(page.getByText(/^You can change this register until /)).toBeVisible();

  // Saved for real: still there after reloading.
  await page.reload();
  await expect(student(page, `Baraka ${name}`).getByLabel("Reason")).toHaveValue("sick");
  await expect(student(page, `Chausiku ${name}`).getByLabel("Late")).toBeChecked();

  // A correction.
  await student(page, `Baraka ${name}`).getByLabel("Present").check();
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(notice(page)).toHaveText("Changes saved.");
  await expect(page.getByText("Present 2, absent 0, late 1")).toBeVisible();

  // The attendance page now shows it taken.
  await page.getByRole("link", { name: "Back to attendance" }).click();
  await expect(page.getByRole("row", { name: new RegExp(`^${className}`) })).toContainText("Taken: present 2, absent 0, late 1");
});

test("a teacher can read but not change a register more than 7 days old", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const { classId, name, ids } = await classOfThree(page);
  const old = kenyaDate(-8);
  const marks = ids.map((id, n) => ({
    student_id: id,
    status: n === 0 ? "absent" : "present",
    reason: n === 0 ? "permission" : null,
  }));
  // Administrators may change any day of a term.
  expect((await call(page, "PUT", `/school/classes/${classId}/attendance/${old}`, { marks })).status).toBe(201);
  await logOut(page);

  await logInAs(page, ATTENDANCE_TEACHER_EMAIL);
  await page.goto(`/classes/${classId}/attendance?date=${old}`);

  await expect(page.getByText("Taken by E2E Attendance Admin on", { exact: false })).toBeVisible();
  await expect(page.getByText("only a school administrator can change its register")).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: `Amani ${name}` })).toContainText(
    "Absent: With permission",
  );
  await expect(page.getByRole("radio")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Save/ })).toHaveCount(0);
});

test("an administrator sees which registers were taken and a term summary", async ({ page }) => {
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const { classId, className, name, ids } = await classOfThree(page);
  for (const [days, absent] of [[-2, 1], [-1, 2]] as const) {
    const marks = ids.map((id, n) => ({
      student_id: id,
      status: n === absent ? "absent" : "present",
      reason: n === absent ? "unknown" : null,
    }));
    expect((await call(page, "PUT", `/school/classes/${classId}/attendance/${kenyaDate(days)}`, { marks })).status).toBe(
      201,
    );
  }

  await page.getByRole("link", { name: "Attendance" }).click();
  // Today: not taken yet.
  await expect(page.getByRole("row", { name: new RegExp(`^${className}`) })).toContainText("Not taken");
  await page.getByLabel("Day").fill(kenyaDate(-1));
  await page.getByRole("button", { name: "Show" }).click();
  await expect(page).toHaveURL(`/attendance?date=${kenyaDate(-1)}`);
  await expect(page.getByRole("row", { name: new RegExp(`^${className}`) })).toContainText(
    "Taken: present 2, absent 1, late 0",
  );
  // A day that has not happened yet.
  await page.goto(`/attendance?date=${kenyaDate(1)}`);
  await expect(page.getByText("Attendance cannot be taken for a day that has not happened yet.")).toBeVisible();

  await page.goto(`/classes/${classId}/attendance/summary`);
  await expect(page.getByRole("heading", { level: 1, name: `${className} attendance` })).toBeVisible();
  await expect(page.getByText("Registers taken on 2 days.", { exact: false })).toBeVisible();
  const baraka = page.getByRole("row", { name: new RegExp(`^Baraka ${name}`) });
  await expect(baraka).toHaveText(new RegExp(`1 / 0\\s*1 \\(1 unknown\\)\\s*50%`));
  await expect(page.getByRole("row", { name: new RegExp(`^Amani ${name}`) })).toContainText("100%");
});

test("a principal reads attendance but takes no registers", async ({ page }) => {
  await logInAs(page, PRINCIPAL_EMAIL);
  await expect(page.getByText("See every class's attendance")).toBeVisible();
  await page.getByRole("link", { name: "Attendance" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Attendance" })).toBeVisible();
  await expect(page.getByLabel("Day")).toHaveValue(kenyaDate());
  await expect(page.getByRole("button", { name: /^Save/ })).toHaveCount(0);
});

test("the register fits a phone screen without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await logInAs(page, ATTENDANCE_ADMIN_EMAIL);
  const { classId, name } = await classOfThree(page);

  await page.goto(`/classes/${classId}/attendance`);
  await student(page, `Amani ${name}`).getByLabel("Absent").check();
  await expect(student(page, `Amani ${name}`).getByLabel("Reason")).toBeVisible();
  for (const path of [`/classes/${classId}/attendance`, "/attendance", `/classes/${classId}/attendance/summary`]) {
    if (path !== `/classes/${classId}/attendance`) {
      await page.goto(path);
      await expect(page.getByRole("table").first()).toBeVisible();
    }
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `${path} scrolls sideways`).toBe(0);
  }
});
