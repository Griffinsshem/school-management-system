import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

// Automatic accessibility checks (D8), shared by accessibility.spec.ts and
// fees.spec.ts: WCAG 2.1 level A and AA with axe-core. No rule is switched
// off; if one ever must be, say why here.

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

// The problems axe finds on the page as it is now, one readable line each:
// empty when the page passes. Results axe marks "needs review" count too
// (some rules, such as duplicate IDs used by screen-reader links, are only
// ever reported that way), so nothing slips through unseen.
export async function problems(page: Page): Promise<string[]> {
  const result = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  const lines = (results: typeof result.violations, kind: string) =>
    results.flatMap((r) =>
      r.nodes.map((n) => `${r.id} (${kind}): ${n.target.join(" ")}: ${(n.failureSummary ?? "").replace(/\s+/g, " ")}`),
    );
  return [...lines(result.violations, "fails"), ...lines(result.incomplete, "needs review")];
}
