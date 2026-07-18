/**
 * Passkey (WebAuthn) browser wrapper — Phase 1 (plan v3).
 *
 * Wraps `navigator.credentials.create()` with:
 *   - base64URL <-> ArrayBuffer conversions (WebAuthn spec uses URL-safe b64 no-pad)
 *   - Server JSON serialization (PublicKeyCredential.toJSON() helper)
 *   - Feature detection (graceful fallback for old browsers)
 *
 * Auth flow (Phase 2) will add `loginWithPasskey()`.
 * Step-up flow (Phase 5) will add `stepUpWithPasskey()`.
 *
 * Usage:
 *   if (isPasskeySupported()) {
 *     const result = await registerPasskey("MacBook Air");
 *     if (result.backup_codes) showBackupCodesModal(result.backup_codes);
 *   }
 */

import { clientFetch, isStepupRequired, type ApiError } from "./api";

// ── Feature detection ──────────────────────────────────────────

export function isPasskeySupported(): boolean {
  return (
    typeof window !== "undefined" &&
    !!window.PublicKeyCredential &&
    typeof navigator !== "undefined" &&
    !!navigator.credentials &&
    typeof navigator.credentials.create === "function"
  );
}

// Detect platform authenticator (TouchID, Windows Hello, etc.)
// Optional UX hint — does NOT affect security.
export async function isPlatformAuthenticatorAvailable(): Promise<boolean> {
  if (!isPasskeySupported()) return false;
  try {
    return await window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
  } catch {
    return false;
  }
}

// ── base64URL helpers (no-pad, URL-safe) ───────────────────────

export function b64urlToBuffer(b64url: string): ArrayBuffer {
  const padded = b64url.replace(/-/g, "+").replace(/_/g, "/");
  const pad = padded.length % 4 === 0 ? "" : "=".repeat(4 - (padded.length % 4));
  const binary = atob(padded + pad);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

export function bufferToB64url(buffer: ArrayBuffer | Uint8Array): string {
  const bytes =
    buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// ── Types matching backend response ────────────────────────────

interface PublicKeyCredentialCreationOptionsJSON {
  challenge: string;
  rp: { id: string; name: string };
  user: { id: string; name: string; displayName: string };
  pubKeyCredParams: { type: "public-key"; alg: number }[];
  timeout?: number;
  excludeCredentials?: { id: string; type: "public-key"; transports?: string[] }[];
  authenticatorSelection?: {
    authenticatorAttachment?: "platform" | "cross-platform";
    residentKey?: "discouraged" | "preferred" | "required";
    requireResidentKey?: boolean;
    userVerification?: "discouraged" | "preferred" | "required";
  };
  attestation?: "none" | "indirect" | "direct" | "enterprise";
}

export interface RegisterFinishResult {
  passkey_id: string;
  device_name: string;
  device_type: "platform" | "cross-platform" | null;
  /** Only present on the FIRST registered Passkey (Improvement #3 — mandatory). */
  backup_codes?: string[];
  backup_codes_must_acknowledge?: boolean;
}

// ── Registration ──────────────────────────────────────────────

function decodeCreationOptions(
  opts: PublicKeyCredentialCreationOptionsJSON
): PublicKeyCredentialCreationOptions {
  return {
    ...opts,
    challenge: b64urlToBuffer(opts.challenge),
    user: { ...opts.user, id: b64urlToBuffer(opts.user.id) },
    excludeCredentials: (opts.excludeCredentials || []).map((c) => ({
      ...c,
      id: b64urlToBuffer(c.id),
      transports: c.transports as AuthenticatorTransport[] | undefined,
    })),
  } as PublicKeyCredentialCreationOptions;
}

function encodeRegistrationCredential(cred: PublicKeyCredential): unknown {
  const response = cred.response as AuthenticatorAttestationResponse;
  const transports =
    typeof response.getTransports === "function" ? response.getTransports() : [];
  return {
    id: cred.id,
    rawId: bufferToB64url(cred.rawId),
    type: cred.type,
    authenticatorAttachment: cred.authenticatorAttachment,
    response: {
      attestationObject: bufferToB64url(response.attestationObject),
      clientDataJSON: bufferToB64url(response.clientDataJSON),
      transports,
    },
    clientExtensionResults: cred.getClientExtensionResults
      ? cred.getClientExtensionResults()
      : {},
  };
}

/**
 * Full registration ceremony.
 * Calls backend /register/start → invokes WebAuthn → posts to /register/finish.
 */
export async function registerPasskey(
  deviceName: string
): Promise<RegisterFinishResult> {
  if (!isPasskeySupported()) {
    throw new Error("เบราว์เซอร์นี้ไม่รองรับ Passkey");
  }
  if (!deviceName?.trim()) {
    throw new Error("กรุณาตั้งชื่ออุปกรณ์");
  }

  // 1. Begin — get challenge + options
  const optionsJSON = await clientFetch<PublicKeyCredentialCreationOptionsJSON>(
    "/account/passkeys/register/start",
    { method: "POST", body: JSON.stringify({}) }
  );

  // 2. Browser ceremony
  const options = decodeCreationOptions(optionsJSON);
  let credential: PublicKeyCredential | null;
  try {
    credential = (await navigator.credentials.create({
      publicKey: options,
    })) as PublicKeyCredential | null;
  } catch (e) {
    // User cancelled / authenticator error — log + rethrow with friendlier msg
    throw new Error(
      `WebAuthn ceremony failed: ${
        e instanceof Error ? e.message : String(e)
      }`
    );
  }
  if (!credential) throw new Error("ไม่ได้รับ credential จากเบราว์เซอร์");

  // 3. Finish — verify on server + save
  const payload = {
    device_name: deviceName.trim(),
    credential: encodeRegistrationCredential(credential),
  };
  return clientFetch<RegisterFinishResult>(
    "/account/passkeys/register/finish",
    { method: "POST", body: JSON.stringify(payload) }
  );
}

// ── Backup codes acknowledge (Improvement #3) ─────────────────

export async function acknowledgeBackupCodes(): Promise<{
  acknowledged: boolean;
  codes_marked: number;
}> {
  return clientFetch<{ acknowledged: boolean; codes_marked: number }>(
    "/account/passkeys/backup-codes/acknowledge",
    { method: "POST", body: JSON.stringify({}) }
  );
}

export interface BackupCodesStatus {
  generation: number;
  total: number;
  used: number;
  remaining: number;
  low: boolean;
  acknowledged: boolean;
}

export async function fetchBackupCodesStatus(): Promise<BackupCodesStatus> {
  return clientFetch<BackupCodesStatus>(
    "/account/passkeys/backup-codes/status"
  );
}

export async function regenerateBackupCodes(): Promise<{
  backup_codes: string[];
  backup_codes_must_acknowledge: boolean;
}> {
  return clientFetch("/account/passkeys/backup-codes/regenerate", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

// ── Admin: passkey overview (read-only + reset) ───────────────

export interface AdminUserPasskeys {
  user_id: string;
  email: string;
  passkeys: {
    id: string;
    device_name: string;
    device_type: string | null;
    created_at: string | null;
    last_used_at: string | null;
    last_used_country: string | null;
    counter_regression_count: number;
  }[];
  count: number;
  backup_codes: { remaining: number; total: number; low: boolean };
}

export async function adminListUserPasskeys(
  userId: string
): Promise<AdminUserPasskeys> {
  return clientFetch<AdminUserPasskeys>(`/admin/users/${userId}/passkeys`);
}

export async function adminResetUserPasskeys(
  userId: string,
  onVerifying?: (active: boolean) => void
): Promise<{ revoked_count: number; message: string }> {
  return mutateWithStepup(
    `/admin/users/${userId}/reset-passkeys`,
    { method: "POST", body: JSON.stringify({}) },
    onVerifying
  );
}

// ── Admin: User 360-degree view (access list + revoke + login history) ──

export interface UserAccessEntry {
  subsystem_id: string;
  subsystem_name: string;
  policy: string; // explicit | all | role | attribute
  source: "explicit" | "policy";
  reason: string; // ป้ายภาษาไทยว่าทำไมถึงมีสิทธิ์
  role: string | null;
  scopes: string[];
  can_revoke: boolean; // true เฉพาะ explicit whitelist entry
  granted_at: string | null;
  granted_by: string | null;
}

export interface GrantableSubsystem {
  subsystem_id: string;
  subsystem_name: string;
}

export interface UserDetailInfo {
  id: string;
  email: string;
  full_name: string | null;
  user_type: string | null;
  status: string | null;
  is_hub_admin: boolean;
  identifier: string | null;
  faculty: string | null;
  major: string | null;
  year_or_position: string | null;
  phone: string | null;
  address: string | null;
  created_at: string | null;
}

export interface UserAccessList {
  user: UserDetailInfo;
  total: number;
  active_count: number;
  subsystems: UserAccessEntry[];
  grantable: GrantableSubsystem[];
}

export interface UserLoginSession {
  id: string;
  subsystem_name: string | null;
  is_hub_direct: boolean;
  ip: string | null;
  geo_country: string | null;
  os_name: string | null;
  browser: string | null;
  device_type: string | null;
  login_method: string | null;
  risk_score: number | null;
  risk_reasons: string[];
  decision: string | null;
  created_at: string | null;
  logout_at: string | null;
  online: boolean;
}

export interface UserSummary {
  failed_logins_7d: number;
  last_login_at: string | null;
  last_risk_event: { created_at: string; risk_score: number | null } | null;
}

export interface UserLoginSessions {
  user_id: string;
  email: string;
  total: number;
  sessions: UserLoginSession[];
}

export async function adminGetUserAccessList(
  userId: string
): Promise<UserAccessList> {
  return clientFetch<UserAccessList>(`/admin/users/${userId}/access-list`);
}

export async function adminGetUserLoginSessions(
  userId: string
): Promise<UserLoginSessions> {
  return clientFetch<UserLoginSessions>(`/admin/users/${userId}/login-sessions`);
}

export async function adminGetUserSummary(userId: string): Promise<UserSummary> {
  return clientFetch<UserSummary>(`/admin/users/${userId}/summary`);
}

export async function adminRevokeUserAccess(
  userId: string,
  subsystemId: string,
  onVerifying?: (active: boolean) => void
): Promise<{ result: string; closed_sessions: number }> {
  return mutateWithStepup(
    `/admin/users/${userId}/access/${subsystemId}`,
    { method: "DELETE" },
    onVerifying
  );
}

export async function adminForceLogoutUser(
  userId: string,
  onVerifying?: (active: boolean) => void
): Promise<{ result: string; closed_sessions: number; revoked_jwt: number }> {
  return mutateWithStepup(
    `/admin/users/${userId}/force-logout`,
    { method: "POST", body: JSON.stringify({}) },
    onVerifying
  );
}

export async function adminGrantUserAccess(
  userId: string,
  subsystemId: string,
  onVerifying?: (active: boolean) => void
): Promise<{ result: string; subsystem_name: string }> {
  return mutateWithStepup(
    `/admin/users/${userId}/access/${subsystemId}`,
    { method: "POST", body: JSON.stringify({}) },
    onVerifying
  );
}

export async function adminDeleteUser(
  userId: string,
  onVerifying?: (active: boolean) => void
): Promise<unknown> {
  return mutateWithStepup(
    `/admin/users/${userId}`,
    { method: "DELETE" },
    onVerifying
  );
}

// ── Lifecycle (Phase 3) ───────────────────────────────────────

export interface PasskeyInfo {
  id: string;
  device_name: string;
  device_type: "platform" | "cross-platform" | null;
  transports: string[];
  created_at: string | null;
  last_used_at: string | null;
  last_used_country: string | null;
  counter_regression_count: number;
  rename_count: number;
}

export interface PasskeyList {
  passkeys: PasskeyInfo[];
  count: number;
  max: number;
}

export async function listPasskeys(): Promise<PasskeyList> {
  return clientFetch<PasskeyList>("/account/passkeys");
}

export async function renamePasskey(
  id: string,
  deviceName: string
): Promise<PasskeyInfo> {
  return clientFetch<PasskeyInfo>(`/account/passkeys/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ device_name: deviceName }),
  });
}

export async function deletePasskey(
  id: string
): Promise<{ deleted: boolean; id: string }> {
  return clientFetch<{ deleted: boolean; id: string }>(
    `/account/passkeys/${id}`,
    { method: "DELETE" }
  );
}

// ── Recovery (Phase 4) — public, no auth ──────────────────────

export async function recoverWithBackupCode(
  email: string,
  code: string
): Promise<{ recovered: boolean; message: string }> {
  return clientFetch("/auth/passkey/recover/backup-code", {
    method: "POST",
    body: JSON.stringify({ email: email.trim(), code: code.trim() }),
  });
}

export async function recoverEmailOtpStart(
  email: string
): Promise<{ sent: boolean; message: string }> {
  return clientFetch("/auth/passkey/recover/email-otp/start", {
    method: "POST",
    body: JSON.stringify({ email: email.trim() }),
  });
}

export async function recoverEmailOtpVerify(
  email: string,
  otp: string
): Promise<{ recovered: boolean; message: string; backup_codes?: string[] }> {
  return clientFetch("/auth/passkey/recover/email-otp/verify", {
    method: "POST",
    body: JSON.stringify({ email: email.trim(), otp: otp.trim() }),
  });
}

// ── Step-up re-auth (Phase 5) ─────────────────────────────────

/**
 * Step-up ด้วย passkey ของ user ปัจจุบัน (JWT required).
 * Throws {detail:{code:"no_passkey"}} ถ้าไม่มี passkey → caller fallback OTP.
 */
export async function stepUpWithPasskey(): Promise<{ granted: boolean; ttl_sec: number }> {
  const optionsJSON = await clientFetch<PublicKeyCredentialRequestOptionsJSON>(
    "/auth/passkey/stepup/start",
    { method: "POST", body: JSON.stringify({}) }
  );
  const options = decodeRequestOptions(optionsJSON);
  const credential = (await navigator.credentials.get({
    publicKey: options,
  })) as PublicKeyCredential | null;
  if (!credential) throw new Error("ไม่ได้รับ credential จากอุปกรณ์");
  return clientFetch("/auth/passkey/stepup/finish", {
    method: "POST",
    body: JSON.stringify({ credential: encodeAssertionCredential(credential) }),
  });
}

/**
 * Inline step-up wrapper (Option C — ไม่ redirect, ไม่เสียข้อมูลในฟอร์ม).
 *
 * รัน mutation; ถ้าเจอ 403 stepup_required → ทำ passkey ceremony ในหน้า
 * (navigator.credentials.get) → retry mutation เดิม 1 ครั้ง.
 *
 * mutation ต้องใช้ clientFetch ด้วย ``stepupMode:"throw"`` เพื่อไม่ให้ interceptor
 * พา redirect ก่อน (ดู lib/api.ts).
 *
 * @param run   ฟังก์ชันที่ทำ mutation (เรียกซ้ำได้ — idempotent ฝั่ง intent)
 * @param onVerifying  callback แจ้ง UI ว่ากำลัง verify (แสดง spinner/ปุ่ม)
 * @throws ApiError {detail:{code:"no_passkey"}} ถ้า user ไม่มี passkey → caller
 *         แสดงข้อความให้ไปตั้งค่า/ใช้ Recovery
 */
export async function runWithStepup<T>(
  run: () => Promise<T>,
  onVerifying?: (active: boolean) => void
): Promise<T> {
  try {
    return await run();
  } catch (e) {
    const err = e as ApiError;
    if (err?.status === 403 && isStepupRequired(err.detail)) {
      onVerifying?.(true);
      try {
        await stepUpWithPasskey(); // inline WebAuthn ceremony → set stepup cache
      } finally {
        onVerifying?.(false);
      }
      return await run(); // retry once — cache ใหม่แล้ว ผ่าน
    }
    throw e;
  }
}

/**
 * Shortcut — mutation + inline step-up ในคำสั่งเดียว.
 *
 * เทียบเท่า: runWithStepup(() => clientFetch(path, {...init, stepupMode:"throw"}))
 * ใช้แทน clientFetch ตรง ๆ ในทุก mutation ที่เป็น critical action (เพิ่ม/ลบ/แก้)
 * เพื่อให้ verify Passkey ในหน้า ไม่ redirect ไม่เสีย state.
 */
export async function mutateWithStepup<T = unknown>(
  path: string,
  init: RequestInit = {},
  onVerifying?: (active: boolean) => void
): Promise<T> {
  return runWithStepup<T>(
    () => clientFetch<T>(path, { ...init, stepupMode: "throw" }),
    onVerifying
  );
}

/**
 * เริ่ม flow "เปลี่ยนบัญชี Google" (re-link) — ต้องผ่าน **passkey** step-up (inline).
 * คืน `start_url` ให้ caller `window.location.href = start_url` เพื่อเริ่ม OAuth กับ
 * บัญชี Google ใหม่ (backend บังคับ passkey เท่านั้น — OTP ไม่ผ่าน).
 * @throws ApiError {detail:{code:"no_passkey"}} → caller แนะนำไป Account Recovery
 */
export async function changeGoogleStart(
  onVerifying?: (active: boolean) => void
): Promise<{ start_url: string }> {
  return mutateWithStepup<{ start_url: string }>(
    "/auth/account/change-google/start",
    { method: "POST" },
    onVerifying
  );
}

export async function stepupOtpStart(): Promise<{ sent: boolean; message: string }> {
  return clientFetch("/auth/stepup/otp/start", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function stepupOtpVerify(
  otp: string
): Promise<{ granted: boolean; ttl_sec: number }> {
  return clientFetch("/auth/stepup/otp/verify", {
    method: "POST",
    body: JSON.stringify({ otp: otp.trim() }),
  });
}

// regenerate codes via OTP — ไม่ revoke passkey (codes หาย/ใกล้หมด)
export async function regenOtpStart(
  email: string
): Promise<{ sent: boolean; message: string }> {
  return clientFetch("/auth/passkey/backup-codes/regen-otp/start", {
    method: "POST",
    body: JSON.stringify({ email: email.trim() }),
  });
}

export async function regenOtpVerify(
  email: string,
  otp: string
): Promise<{ regenerated: boolean; message: string; backup_codes: string[] }> {
  return clientFetch("/auth/passkey/backup-codes/regen-otp/verify", {
    method: "POST",
    body: JSON.stringify({ email: email.trim(), otp: otp.trim() }),
  });
}

// ── Authentication (Phase 2 — email-first) ────────────────────

interface PublicKeyCredentialRequestOptionsJSON {
  challenge: string;
  rpId?: string;
  timeout?: number;
  userVerification?: "discouraged" | "preferred" | "required";
  allowCredentials?: {
    id: string;
    type: "public-key";
    transports?: string[];
  }[];
}

export interface LoginResult {
  access_token: string;
  token_type: "bearer";
  user: {
    id: string;
    email: string;
    full_name: string | null;
    user_type: string | null;
    is_hub_admin: boolean;
  };
  /** Counter-regression notice (Improvement #10) — not blocking, UI may show a subtle hint. */
  notice?: "passkey_counter_regression";
}

function decodeRequestOptions(
  opts: PublicKeyCredentialRequestOptionsJSON
): PublicKeyCredentialRequestOptions {
  return {
    ...opts,
    challenge: b64urlToBuffer(opts.challenge),
    allowCredentials: (opts.allowCredentials || []).map((c) => ({
      ...c,
      id: b64urlToBuffer(c.id),
      transports: c.transports as AuthenticatorTransport[] | undefined,
    })),
  } as PublicKeyCredentialRequestOptions;
}

function encodeAssertionCredential(cred: PublicKeyCredential): unknown {
  const response = cred.response as AuthenticatorAssertionResponse;
  return {
    id: cred.id,
    rawId: bufferToB64url(cred.rawId),
    type: cred.type,
    authenticatorAttachment: cred.authenticatorAttachment,
    response: {
      authenticatorData: bufferToB64url(response.authenticatorData),
      clientDataJSON: bufferToB64url(response.clientDataJSON),
      signature: bufferToB64url(response.signature),
      userHandle: response.userHandle
        ? bufferToB64url(response.userHandle)
        : null,
    },
    clientExtensionResults: cred.getClientExtensionResults
      ? cred.getClientExtensionResults()
      : {},
  };
}

/**
 * Discoverable login (Phase 7) — ไม่ต้องกรอก email.
 * browser โชว์ resident keys → identify จาก userHandle.
 */
export async function loginWithPasskeyDiscoverable(): Promise<LoginResult> {
  if (!isPasskeySupported()) throw new Error("เบราว์เซอร์นี้ไม่รองรับ Passkey");
  const optionsJSON = await clientFetch<PublicKeyCredentialRequestOptionsJSON>(
    "/auth/passkey/login/discoverable/start",
    { method: "POST", body: JSON.stringify({}) }
  );
  const options = decodeRequestOptions(optionsJSON);
  const credential = (await navigator.credentials.get({
    publicKey: options,
  })) as PublicKeyCredential | null;
  if (!credential) throw new Error("ไม่ได้รับ credential จากเบราว์เซอร์");
  return clientFetch<LoginResult>("/auth/passkey/login/discoverable/finish", {
    method: "POST",
    body: JSON.stringify({ credential: encodeAssertionCredential(credential) }),
  });
}

/**
 * Full Passkey login ceremony.
 * Calls /login/start with email → invokes WebAuthn get() → /login/finish.
 *
 * Throws if browser doesn't support, user cancels, or backend rejects.
 */
export async function loginWithPasskey(email: string): Promise<LoginResult> {
  if (!isPasskeySupported()) {
    throw new Error("เบราว์เซอร์นี้ไม่รองรับ Passkey");
  }
  const trimmed = email.trim();
  if (!trimmed) throw new Error("กรุณากรอก email");

  // 1. Begin — get challenge + allowCredentials
  const optionsJSON = await clientFetch<PublicKeyCredentialRequestOptionsJSON>(
    "/auth/passkey/login/start",
    { method: "POST", body: JSON.stringify({ email: trimmed }) }
  );

  // 2. Browser ceremony
  const options = decodeRequestOptions(optionsJSON);
  let credential: PublicKeyCredential | null;
  try {
    credential = (await navigator.credentials.get({
      publicKey: options,
    })) as PublicKeyCredential | null;
  } catch (e) {
    throw new Error(
      `Passkey ceremony failed: ${
        e instanceof Error ? e.message : String(e)
      }`
    );
  }
  if (!credential) throw new Error("ไม่ได้รับ credential จากเบราว์เซอร์");

  // 3. Finish — verify + issue token
  return clientFetch<LoginResult>(
    "/auth/passkey/login/finish",
    {
      method: "POST",
      body: JSON.stringify({
        email: trimmed,
        credential: encodeAssertionCredential(credential),
      }),
    }
  );
}
