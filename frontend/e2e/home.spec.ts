import { expect, test, type Locator, type Page } from "@playwright/test";

import { problems } from "./axe";
import { offScreen } from "./fees-data";
import { SCHOOL_A, SCHOOL_B, SCHOOL_B_CHOICE, logIn, logInToSchoolA } from "./helpers";

// The school chooser and the home page's heading (H1). The E2E admin is a
// school administrator in E2E School A (Nairobi City) and a teacher in E2E
// School B (Mombasa), so each card must show the role in that school.

async function toChooser(page: Page) {
  await page.goto("/login");
  await logIn(page);
  await expect(page.getByRole("heading", { level: 1, name: "Choose a school" })).toBeVisible();
}

function card(page: Page, school: string): Locator {
  return page.getByRole("main").getByRole("button", { name: new RegExp(`^${school} `) });
}

// The crest's initials: drawn for the eye, hidden from screen readers.
async function crest(button: Locator): Promise<{ text: string; hidden: string | null }> {
  const shield = button.locator('[aria-hidden="true"]').first();
  return { text: (await shield.innerText()).trim(), hidden: await shield.getAttribute("aria-hidden") };
}

test("the chooser greets, explains and shows each school's county and role on their own lines", async ({ page }) => {
  await toChooser(page);
  const main = page.getByRole("main");
  await expect(main.getByText(/^Good (morning|afternoon|evening), E2E Admin$/)).toBeVisible();
  await expect(main.getByText("You belong to 2 schools. Choose one to open; you can switch later from the home page.")).toBeVisible();

  const a = card(page, SCHOOL_A);
  const b = card(page, SCHOOL_B);
  await expect(a).toHaveAccessibleName(`${SCHOOL_A} Nairobi City County Your role: School administrator Open`);
  await expect(b).toHaveAccessibleName(`${SCHOOL_B} Mombasa County Your role: Teacher Open`);

  // Name, county and role are separate lines, never run together.
  const name = a.getByText(SCHOOL_A, { exact: true });
  const county = a.getByText("Nairobi City County", { exact: true });
  const role = a.getByText(/^Your role:/);
  const [n, c, r] = await Promise.all([name.boundingBox(), county.boundingBox(), role.boundingBox()]);
  expect(c!.y).toBeGreaterThanOrEqual(n!.y + n!.height - 1);
  expect(r!.y).toBeGreaterThanOrEqual(c!.y + c!.height - 1);
  expect(c!.x).toBeCloseTo(n!.x, 0);

  expect(await crest(a)).toEqual({ text: "EA", hidden: "true" });
  expect(await crest(b)).toEqual({ text: "EB", hidden: "true" });
});

test("choosing a school says it is opening, then shows the school with its crest", async ({ page }) => {
  await toChooser(page);
  // Hold the answer back until the page has shown that it is waiting.
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/api/v1/auth/active-school", async (route) => {
    await held;
    await route.continue();
  });

  await card(page, SCHOOL_B).click();
  await expect(page.getByRole("status")).toHaveText(`Opening ${SCHOOL_B}...`);
  await expect(card(page, SCHOOL_B)).toContainText("Opening...");
  await expect(card(page, SCHOOL_A)).toBeDisabled();
  release();

  const heading = page.getByRole("heading", { level: 1, name: SCHOOL_B });
  await expect(heading).toBeVisible();
  await expect(page.getByRole("main").getByText("Mombasa County", { exact: true })).toBeVisible();
  const shield = page.getByRole("main").locator('[aria-hidden="true"]').first();
  await expect(shield).toHaveText("EB");
});

test("the switch list names each school's county", async ({ page }) => {
  await logInToSchoolA(page);
  const options = page.getByLabel("Switch school").locator("option");
  await expect(options).toHaveText(["E2E School A (Nairobi City)", SCHOOL_B_CHOICE]);
});

test("the switch box is wide enough for a school's name and county", async ({ page }) => {
  await logInToSchoolA(page);
  // Staging's longest choice, which a narrower box cut to "(Momb".
  const longest = "Staging Demo School B (Mombasa)";
  const room = await page.getByLabel("Switch school").evaluate((select, text) => {
    const style = getComputedStyle(select);
    const context = document.createElement("canvas").getContext("2d")!;
    context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
    const inside = select.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    // About 1.5rem of the box is the drop-down arrow.
    return inside - 24 - context.measureText(text).width;
  }, longest);
  expect(room).toBeGreaterThanOrEqual(0);
});

// Words of the band's title that are split over two lines.
async function splitWords(page: Page): Promise<string[]> {
  return page
    .getByRole("banner")
    .locator("p")
    .first()
    .evaluate((title) => {
      const split: string[] = [];
      const walker = document.createTreeWalker(title, NodeFilter.SHOW_TEXT);
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const text = node.textContent ?? "";
        for (const match of text.matchAll(/\S+/g)) {
          const range = document.createRange();
          range.setStart(node, match.index);
          range.setEnd(node, match.index + match[0].length);
          const lines = new Set(Array.from(range.getClientRects()).map((r) => Math.round(r.top)));
          if (lines.size > 1) {
            split.push(match[0]);
          }
        }
      }
      return split;
    });
}

test("the chooser fits a phone screen, with every card on screen", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 740 });
  await toChooser(page);
  // With the site's own font the band keeps one row: the product's name
  // beside Menu and Log out.
  const band = page.getByRole("banner");
  const [title, logOut] = await Promise.all([
    band.locator("p").first().boundingBox(),
    band.getByRole("button", { name: "Log out" }).boundingBox(),
  ]);
  expect(logOut!.y).toBeLessThan(title!.y + title!.height);
  await page.addStyleTag({ content: 'body { font-family: "DejaVu Sans", Verdana, sans-serif !important; }' });
  expect(await offScreen(page)).toEqual([]);
  // With no school open the band's title is the product's name: no word of
  // it may break across lines beside Menu and Log out ("Manageme / nt").
  await expect(page.getByRole("banner").locator("p").first()).toHaveText("School Management System");
  expect(await splitWords(page)).toEqual([]);
  for (const name of ["Menu", "Log out"]) {
    const box = await page.getByRole("banner").getByRole("button", { name }).boundingBox();
    expect(box!.x + box!.width, name).toBeLessThanOrEqual(320);
  }
  for (const school of [SCHOOL_A, SCHOOL_B]) {
    const box = await card(page, school).boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(320);
    // Large enough to tap.
    expect(box!.height).toBeGreaterThanOrEqual(64);
  }
});

for (const scheme of ["light", "dark"] as const) {
  test(`the chooser and home heading pass the accessibility checks (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await toChooser(page);
    const found = (await problems(page)).map((p) => `chooser: ${p}`);
    await page.setViewportSize({ width: 320, height: 740 });
    found.push(...(await problems(page)).map((p) => `chooser on a phone: ${p}`));
    await page.setViewportSize({ width: 1280, height: 720 });
    await card(page, SCHOOL_A).click();
    await expect(page.getByRole("heading", { level: 1, name: SCHOOL_A })).toBeVisible();
    found.push(...(await problems(page)).map((p) => `home: ${p}`));
    expect(found).toEqual([]);
  });
}
