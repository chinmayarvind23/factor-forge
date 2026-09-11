import { defineConfig } from "@playwright/test";

// Callers select a fresh evidence directory so repeated runs never overwrite prior evidence.
const outputDir = process.env.FACTORFORGE_E2E_OUTPUT ?? "test-results";
export default defineConfig({
  testDir: ".",
  testMatch: "*.spec.ts",
  outputDir,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45000,
  reporter: [["list"], ["json", { outputFile: `${outputDir}/results.json` }]],
  use: {
    baseURL: "http://127.0.0.1:3001",
    browserName: "chromium",
    video: "on",
    screenshot: "on",
    trace: "on",
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 1100 } } },
    {
      name: "mobile",
      use: {
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
});
