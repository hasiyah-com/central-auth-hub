import { test } from "node:test";
import assert from "node:assert/strict";
import { generateVerifier, challengeFor } from "../src/pkce.js";

test("verifier length in valid range", () => {
  const v = generateVerifier(64);
  assert.ok(v.length >= 43 && v.length <= 128);
});

test("verifier uses base64url charset", () => {
  const v = generateVerifier(64);
  assert.match(v, /^[A-Za-z0-9_-]+$/);
});

test("two verifiers differ", () => {
  assert.notStrictEqual(generateVerifier(64), generateVerifier(64));
});

test("rejects too short length", () => {
  assert.throws(() => generateVerifier(32), RangeError);
});

test("rejects too long length", () => {
  assert.throws(() => generateVerifier(200), RangeError);
});

test("challenge matches RFC 7636 §4.2 vector", () => {
  // RFC 7636 Appendix B test vector
  const verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"; // pragma: allowlist secret
  const challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"; // pragma: allowlist secret
  assert.strictEqual(challengeFor(verifier), challenge);
});

test("challenge is deterministic", () => {
  assert.strictEqual(challengeFor("abc123"), challengeFor("abc123"));
});
