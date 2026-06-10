import { randomBytes, timingSafeEqual } from "node:crypto";
import { StateError } from "./errors.js";

/** Generate 32-char hex random state (16 bytes). */
export function generateState(): string {
  return randomBytes(16).toString("hex");
}

/** Constant-time compare — throws StateError on mismatch. */
export function verifyState(expected: string, provided: string): void {
  if (!expected) throw new StateError("No state to verify (session expired?)");
  const a = Buffer.from(expected);
  const b = Buffer.from(provided);
  if (a.length !== b.length || !timingSafeEqual(a, b)) {
    throw new StateError("State mismatch — possible CSRF attack");
  }
}
