import { test } from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { verifyWebhook } from "../src/webhookReceiver.js";
import { HubError } from "../src/errors.js";

function sig(body: string, key: string): string {
  return createHmac("sha256", key).update(body).digest("hex");
}

test("valid signature accepts", () => {
  const body = JSON.stringify({ event: "access_revoked", hub_user_id: "u1" });
  const ts = String(Math.floor(Date.now() / 1000));
  const key = "k";
  const payload = verifyWebhook(key, body, {
    "X-Hub-Signature-256": sig(body, key),
    "X-Hub-Timestamp": ts,
  });
  assert.strictEqual(payload.event, "access_revoked");
  assert.strictEqual(payload.hub_user_id, "u1");
});

test("bad signature rejects", () => {
  const body = '{"x":1}';
  const ts = String(Math.floor(Date.now() / 1000));
  assert.throws(
    () =>
      verifyWebhook("k", body, {
        "X-Hub-Signature-256": "a".repeat(64),
        "X-Hub-Timestamp": ts,
      }),
    /signature mismatch/i
  );
});

test("expired timestamp rejects", () => {
  const body = '{"x":1}';
  const ts = String(Math.floor(Date.now() / 1000) - 600);
  assert.throws(
    () =>
      verifyWebhook("k", body, {
        "X-Hub-Signature-256": sig(body, "k"),
        "X-Hub-Timestamp": ts,
      }),
    /out of tolerance/i
  );
});

test("missing headers rejects", () => {
  assert.throws(() => verifyWebhook("k", "{}", {}), HubError);
});

test("bad timestamp format", () => {
  assert.throws(
    () =>
      verifyWebhook("k", "{}", {
        "X-Hub-Signature-256": "x",
        "X-Hub-Timestamp": "not-a-number",
      }),
    /timestamp format/i
  );
});

test("case-insensitive headers", () => {
  const body = '{"y":2}';
  const ts = String(Math.floor(Date.now() / 1000));
  const payload = verifyWebhook("k", body, {
    "x-hub-signature-256": sig(body, "k"),
    "x-hub-timestamp": ts,
  });
  assert.strictEqual(payload.y, 2);
});
