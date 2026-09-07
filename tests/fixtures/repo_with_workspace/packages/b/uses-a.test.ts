import { expect, test } from "vitest";
import { sum } from "@fixture/a";

test("resolves the workspace package from its own node_modules", () => {
  expect(sum(2, 2)).toBe(4);
});
