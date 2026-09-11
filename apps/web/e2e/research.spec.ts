import { expect, test } from "@playwright/test";

/** Exercise real browser CORS, submission, polling and the rendered normalized record. */
test("creates a brief through the real API", async ({ page }, info) => {
  const failures: string[] = [];
  // Runtime exceptions are stronger evidence than a screenshot alone.
  page.on("pageerror", (error) => failures.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Your research idea" }),
  ).toBeVisible();
  await page.screenshot({
    path: info.outputPath("initial.png"),
    fullPage: true,
  });
  await page
    .getByLabel("What would you like to investigate?")
    .fill("  Test   momentum\n after sector neutralization.  ");
  const receiptPromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/api/v1/research-runs"),
  );
  await page.getByRole("button", { name: "Create research brief" }).click();
  const receipt = await receiptPromise;
  expect(receipt.status()).toBe(202);
  const body = await receipt.json();
  expect(body.status).toBe("RECEIVED");
  expect(receipt.request().headers()["idempotency-key"]).toMatch(
    /^[0-9a-f-]{36}$/,
  );
  await expect(page.getByText("Brief ready", { exact: true })).toBeVisible();
  await expect(page.locator(".brief p")).toHaveText(
    "Test momentum after sector neutralization.",
  );
  await expect(page.locator(".run-id code")).toHaveText(body.run_id);
  await expect(page.locator(".timeline .done")).toHaveCount(2);
  await expect(
    page.getByText("No factor performance has been measured.", {
      exact: false,
    }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  expect(failures).toEqual([]);
  await page.screenshot({
    path: info.outputPath("brief-ready.png"),
    fullPage: true,
  });
  // A deliberate new run after success gets a new identity, even with identical inputs.
  const secondReceipt = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/api/v1/research-runs"),
  );
  await page.getByRole("button", { name: "Create research brief" }).click();
  const secondBody = await (await secondReceipt).json();
  expect(secondBody.run_id).not.toBe(body.run_id);
  await expect(page.locator(".run-id code")).toHaveText(secondBody.run_id);
});

/** An uncertain failed POST must show a failure and reuse its key on recovery. */
test("API failure stays honest and retry preserves request identity", async ({
  page,
}, info) => {
  const keys: string[] = [];
  let failNext = true;
  // Fail only the first write; recovery uses the real backend and normal browser security.
  await page.route(
    "http://127.0.0.1:8001/api/v1/research-runs",
    async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      keys.push(route.request().headers()["idempotency-key"] ?? "");
      if (failNext) {
        failNext = false;
        await route.abort("connectionfailed");
      } else await route.continue();
    },
  );
  await page.goto("/");
  await page
    .getByRole("button", { name: "Try a momentum research idea" })
    .click();
  await page.getByRole("button", { name: "Create research brief" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Something needs attention" }),
  ).toContainText("The local API did not respond");
  await expect(page.getByText("Brief ready", { exact: true })).toHaveCount(0);
  await page.screenshot({
    path: info.outputPath("api-unavailable.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Create research brief" }).click();
  await expect(page.getByText("Brief ready", { exact: true })).toBeVisible();
  expect(keys).toHaveLength(2);
  expect(keys[0]).not.toBe("");
  expect(keys[0]).toBe(keys[1]);
  await page.screenshot({
    path: info.outputPath("retry-recovered.png"),
    fullPage: true,
  });
});
