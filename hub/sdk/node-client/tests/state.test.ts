import { test } from "node:test";
import assert from "node:assert/strict";
import { generateState, verifyState } from "../src/state.js";
import { StateError } from "../src/errors.js";

test("generate 32 hex chars", () => {
  const s = generateState();
  assert.strictEqual(s.length, 32);
  assert.match(s, /^[0-9a-f]{32}$/);
});

test("matching state passes", () => {
  verifyState("abc123", "abc123"); // no throw
});

test("mismatch raises StateError", () => {
  assert.throws(() => verifyState("expected", "attacker"), StateError);
});

test("missing expected state raises", () => {
  assert.throws(() => verifyState("", "anything"), StateError);
});

test("timing-safe — different length", () => {
  assert.throws(() => verifyState("short", "longer-value"), StateError);
});

test("timing-safe — same length differ", () => {
  assert.throws(() => verifyState("abcd1234", "abcd1235"), StateError);
});
