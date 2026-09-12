import { expect, test } from "@playwright/test";

const demo = process.env.FACTORFORGE_DEMO_URL;
test.skip(!demo, "Set FACTORFORGE_DEMO_URL to the built static demo.");

test("inspect completed accounting and the precision guard", async ({
  page,
}, testInfo) => {
  // Exercise the published artifact paths and rendered values, not duplicated UI fixtures.
  await page.goto(demo ?? "");
  await expect(page.locator("#status")).toHaveText("Completed");
  await expect(page.locator("#metrics")).toContainText("$1,057.98");
  await expect(page.locator("#fills tr")).toHaveCount(4);
  await expect(page.locator("#fills")).not.toContainText("undefined");
  await expect(page.locator("#integrity")).toContainText(
    "verified in your browser",
  );
  await page
    .getByRole("button", { name: "An execution guard in action" })
    .click();
  await expect(page.locator("#status")).toHaveText("Guard applied");
  await expect(page.locator("#decision")).toContainText(
    "FUNDING_QUANTITY_PRECISION",
  );
  await expect(page.locator("#fills")).toContainText("No trades dispatched.");
  await expect(page.locator("#metrics")).toContainText("No trades");
  await page.getByRole("button", { name: "A two-signal hybrid" }).click();
  await expect(page.locator("#status")).toHaveText("Completed");
  await expect(page.locator("#decision")).toContainText(
    "75% score and 25% quality",
  );
  await expect(page.locator("#metrics")).toContainText("$1,057.98");
  await expect(page.locator("#raw")).toContainText("quality");
  await page.getByRole("button", { name: "A validated twelve-return path" }).click();
  await expect(page.locator("#metrics")).toContainText("$1,107.89");
  await expect(page.locator("#validation-summary")).toContainText("12 executed return intervals feed 3 contiguous test blocks");
  await expect(page.locator("#validation-download")).toHaveAttribute("href", /objects\/sha256\//);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("validation.png"), fullPage: true });
});

test("modified validation bytes clear the prior result", async ({ page }) => {
  // The linked validation record has its own integrity check after a valid initial result.
  const manifestResponse = page.waitForResponse((response) => response.url().endsWith("/evidence.json"));
  await page.goto(demo ?? "");
  await expect(page.locator("#status")).toHaveText("Completed");
  const manifest = await (await manifestResponse).json();
  const ref = manifest.cases.find((row: { id: string }) => row.id === "validation").validation;
  await page.route(`**/objects/sha256/${ref.sha256.slice(0, 2)}/${ref.sha256}`, (route) => route.fulfill({ body: "{}" }));
  await page.getByRole("button", { name: "A validated twelve-return path" }).click();
  await expect(page.locator("#title")).toHaveText("Evidence could not be loaded");
  await expect(page.locator("#status")).toBeEmpty();
  await expect(page.locator("#validation-panel")).toBeHidden();
});

test("modified execution bytes cannot appear as a verified result", async ({
  page,
}) => {
  // Corrupt the actual network response while retaining the original manifest identity.
  await page.route("**/objects/sha256/**", (route) =>
    route.fulfill({ body: "{}" }),
  );
  await page.goto(demo ?? "");
  await expect(page.locator("#title")).toHaveText(
    "Evidence could not be loaded",
  );
  await expect(page.locator("#integrity")).toContainText("did not match");
  await expect(page.locator("#status")).toBeEmpty();
});
