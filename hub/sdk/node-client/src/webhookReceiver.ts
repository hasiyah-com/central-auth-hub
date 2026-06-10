import { createHmac, timingSafeEqual } from "node:crypto";
import { HubError } from "./errors.js";

interface NormalizedHeaders {
  [k: string]: string | undefined;
}

/** Verify HMAC-SHA256 webhook from Hub. */
export function verifyWebhook(
  sharedKey: string,
  rawBody: Buffer | string,
  headers: Record<string, string | string[] | undefined>,
  maxAgeSec = 300
): Record<string, unknown> {
  const h: NormalizedHeaders = {};
  for (const [k, v] of Object.entries(headers)) {
    if (v === undefined) continue;
    h[k.toLowerCase()] = Array.isArray(v) ? v[0] : v;
  }
  const sig = h["x-hub-signature-256"];
  const ts = h["x-hub-timestamp"];
  if (!sig || !ts) throw new HubError("Missing X-Hub-Signature-256 or X-Hub-Timestamp");

  const tsInt = parseInt(ts, 10);
  if (isNaN(tsInt)) throw new HubError("Bad timestamp format");
  if (Math.abs(Math.floor(Date.now() / 1000) - tsInt) > maxAgeSec) {
    throw new HubError(`Webhook timestamp out of tolerance (${maxAgeSec}s)`);
  }

  const body = typeof rawBody === "string" ? Buffer.from(rawBody) : rawBody;
  const expected = createHmac("sha256", sharedKey).update(body).digest("hex");
  const a = Buffer.from(expected);
  const b = Buffer.from(sig);
  if (a.length !== b.length || !timingSafeEqual(a, b)) {
    throw new HubError("Webhook signature mismatch");
  }

  try {
    return JSON.parse(body.toString("utf-8"));
  } catch (e) {
    throw new HubError(`Body not valid JSON: ${(e as Error).message}`);
  }
}
