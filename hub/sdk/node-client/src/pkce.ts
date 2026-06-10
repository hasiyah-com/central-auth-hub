import { createHash, randomBytes } from "node:crypto";

/** Base64url-encode without padding (RFC 7636 §4.2). */
function b64url(buf: Buffer): string {
  return buf.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/**
 * Generate code_verifier (RFC 7636 §4.1) — 43..128 chars.
 */
export function generateVerifier(length = 64): string {
  if (length < 43 || length > 128) {
    throw new RangeError("verifier length must be 43..128");
  }
  return b64url(randomBytes(length));
}

/** code_challenge = BASE64URL(SHA256(verifier)) — RFC 7636 §4.2 */
export function challengeFor(verifier: string): string {
  return b64url(createHash("sha256").update(verifier).digest());
}
