import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { chromium, expect } from "@playwright/test";

// Record real rendered evidence with deliberate reading time, without replacing page content.
const target = process.env.FACTORFORGE_DEMO_URL;
const destination = process.env.FACTORFORGE_DEMO_RECORDING;
if (!target || !destination)
  throw new Error("Set demo URL and a fresh recording directory.");
await mkdir(destination, { recursive: false });
const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  recordVideo: { dir: destination, size: { width: 1440, height: 1000 } },
});
const page = await context.newPage();
const errors: string[] = [];
page.on("pageerror", (error) => errors.push(error.message));
const scenes: { label: string; status: string }[] = [];
try {
  await page.goto(target, { waitUntil: "networkidle", timeout: 45000 });
  await expect(page.locator("#status")).toHaveText("Completed");
  await expect(page.locator("#integrity")).toContainText(
    "verified in your browser",
  );
  await expect(page.locator("#metrics")).toContainText("$1,057.98");
  await page.screenshot({
    path: path.join(destination, "overview.png"),
    fullPage: true,
  });
  await page.waitForTimeout(5000);
  for (const [label, status, expected] of [
    ["A two-signal hybrid", "Completed", "$1,057.98"],
    ["A validated twelve-return path", "Completed", "$1,107.89"],
    ["An execution guard in action", "Guard applied", "No trades"],
  ]) {
    await page.getByRole("button", { name: label }).click();
    await expect(page.locator("#status")).toHaveText(status);
    await expect(page.locator("#metrics")).toContainText(expected);
    scenes.push({ label, status });
    await page.waitForTimeout(5000);
    if (label.includes("twelve")) {
      await page.locator("#validation-panel").scrollIntoViewIfNeeded();
      await expect(page.locator("#validation-summary")).toContainText(
        "3 contiguous test blocks",
      );
      await page.waitForTimeout(5000);
      await page.getByRole("button", { name: label }).scrollIntoViewIfNeeded();
    }
  }
  if (errors.length) throw new Error("Browser reported script errors.");
} finally {
  await context.close();
  await browser.close();
}
const video = page.video();
if (!video) throw new Error("Recording did not produce a video.");
await writeFile(
  path.join(destination, "recording.json"),
  JSON.stringify(
    {
      url: target,
      savedEvidence: true,
      liveInference: false,
      initialStatus: "Completed",
      scenes,
      pageErrors: errors,
      video: await video.path(),
    },
    null,
    2,
  ),
);
console.log("Verified demo recording saved.");
