import { expect, test } from "vitest";
import { sum } from "../src/index";

test("sums", () => {
  expect(sum(1, 2)).toBe(3);
});
