import { test } from "node:test";
import assert from "node:assert/strict";
import { Config } from "../src/config.js";
import { HubError } from "../src/errors.js";

test("valid config builds", () => {
  const c = new Config({
    hubUrl: "http://localhost:8000",
    clientId: "cli_x",
    clientSecret: "sec_x", // pragma: allowlist secret
    redirectUri: "http://localhost/cb",
  });
  assert.strictEqual(c.hubUrl, "http://localhost:8000");
  assert.deepStrictEqual(c.scope, ["openid", "profile", "email"]);
  assert.strictEqual(c.jwksCacheTtl, 600);
});

test("trailing slash stripped", () => {
  const c = new Config({
    hubUrl: "http://localhost:8000/",
    clientId: "x",
    clientSecret: "y",
    redirectUri: "z",
  });
  assert.strictEqual(c.hubUrl, "http://localhost:8000");
});

test("missing clientId raises", () => {
  assert.throws(
    () =>
      new Config({
        hubUrl: "http://x",
        clientId: "",
        clientSecret: "y",
        redirectUri: "z",
      }),
    HubError
  );
});

test("custom scope used", () => {
  const c = new Config({
    hubUrl: "http://x",
    clientId: "x",
    clientSecret: "y",
    redirectUri: "z",
    scope: ["email", "student_id"],
  });
  assert.deepStrictEqual(c.scope, ["email", "student_id"]);
});
