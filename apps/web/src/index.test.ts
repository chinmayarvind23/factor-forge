import { expect, test } from "bun:test";
import { productName } from "./index";

/** Exercise the actual module resolver before adding the browser/API contract. */
test("web module imports", () => {
  expect(productName).toBe("FactorForge");
});
