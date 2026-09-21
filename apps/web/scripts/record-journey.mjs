import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { chromium, expect } from "@playwright/test";

// Record the rendered replay with explicit scope labels and evidence-derived assertions.
const target = process.env.FACTORFORGE_DEMO_URL;
const destination = process.env.FACTORFORGE_DEMO_RECORDING;
if (!target || !destination)
  throw new Error("Set target URL and fresh recording directory");
const check = process.argv.includes("--check");
await mkdir(destination, { recursive: false });
const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  ...(check
    ? {}
    : {
        recordVideo: { dir: destination, size: { width: 1440, height: 1000 } },
      }),
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const scenes = [];
try {
  await page.goto(target, { waitUntil: "networkidle" });
  await expect(page.locator("#integrity")).toContainText("verified at build");
  await page
    .locator("#idea")
    .pressSequentially("Investigate the original monthly score strategy", {
      delay: check ? 0 : 55,
    });
  await expect(page.locator("#idea")).toHaveValue(
    "Investigate the original monthly score strategy",
  );
  if (!check) await page.waitForTimeout(4500);
  await page.screenshot({ path: path.join(destination, "00-idea.png") });
  scenes.push("Recorded idea entered; replay scope visible");
  for (const [index, heading, content] of [
    [1, "Retrieve a source with explicit rules.", "long the high-score"],
    [2, "Inspect what the model extracted.", "long_low_short_high"],
    [3, "Compile an executable strategy.", "6 bps commission + 4 bps slippage"],
    [
      4,
      "The execution guard stops the attempt.",
      "MONTHLY_BORROW_UNAVAILABLE_OR_AMBIGUOUS",
    ],
    [5, "Explain the outcome. Keep the evidence.", "48 reachable artifacts"],
    [6, "Compare with the authored reference.", "$1,057.98"],
  ]) {
    await page.locator("#next").click();
    await expect(page.locator("#title")).toHaveText(heading);
    await expect(page.locator("#content")).toContainText(content);
    await expect(page.locator(".badge")).toContainText("EVIDENCE REPLAY");
    if (
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      )
    )
      throw new Error("Horizontal overflow");
    await page.screenshot({
      path: path.join(destination, `0${index}-scene.png`),
      fullPage: true,
    });
    scenes.push(heading);
    if (!check)
      await page.waitForTimeout(index === 1 || index === 2 ? 9500 : 7500);
  }
  await expect(page.locator("#intro")).toContainText(
    "not a correction by the agent",
  );
  if (check) {
    await page.setViewportSize({ width: 390, height: 844 });
    if (
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      )
    )
      throw new Error("Mobile overflow");
    await page.screenshot({
      path: path.join(destination, "mobile.png"),
      fullPage: true,
    });
  }
  if (errors.length) throw new Error(errors.join("\n"));
} finally {
  await context.close();
  await browser.close();
}
await writeFile(
  path.join(destination, "recording.json"),
  JSON.stringify(
    {
      url: target,
      scope:
        "Real browser recording of retained evidence replay on authored inputs",
      liveInference: false,
      scenes,
      pageErrors: errors,
      video: check ? null : await page.video().path(),
    },
    null,
    2,
  ),
);
console.log(
  JSON.stringify({
    status: "passed",
    scenes: scenes.length,
    recording: !check,
    destination,
  }),
);
