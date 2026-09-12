import { expect, test } from "@playwright/test";

const demo = process.env.FACTORFORGE_DEMO_URL;
test.skip(!demo, "Set FACTORFORGE_DEMO_URL to the built static demo.");

test("inspect completed accounting and the precision guard", async ({
  page,
}) => {
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
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
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
