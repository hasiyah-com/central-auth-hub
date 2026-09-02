"use client";

/**
 * Passkey recovery + regenerate (Phase 4 + lifecycle).
 *   - Backup Code → revoke passkey
 *   - Email OTP   → revoke passkey + codes ใหม่
 *   - ขอ codes ใหม่ → regenerate codes (ไม่แตะ passkey)
 * codes ใหม่ → CodesAck (copy/download/checkbox/ยืนยัน → login).
 *
 * return_to: ถ้ามาจาก subsystem flow → ?return_to=<url> ให้กลับไป login ของ subsystem
 *   เพื่อกัน open-redirect: รับเฉพาะ path relative ('/...') หรือ URL ที่ hostname
 *   ตรงกับ Hub origin (subsystem ใน dev อยู่บน localhost คนละ port → match แล้ว)
 */

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  recoverEmailOtpStart,
  recoverEmailOtpVerify,
  recoverWithBackupCode,
  recoverWithTotp,
  submitRecoveryRequest,
  regenOtpStart,
  regenOtpVerify,
} from "@/lib/passkey";
import { CodesAck } from "./_CodesAck";

type Tab = "backup" | "otp" | "regen" | "totp" | "ticket";

const HUB_URL = process.env.NEXT_PUBLIC_HUB_URL || "http://localhost:8000";

/** Allow return_to เฉพาะ relative path หรือ URL ที่ hostname เดียวกับ Hub
 *  (ครอบคลุม subsystem ใน dev: localhost:8001/8002 — hostname=localhost เหมือนกัน) */
function safeReturnTo(raw: string | null): string {
  if (!raw) return "/auth/login";
  if (raw.startsWith("/") && !raw.startsWith("//")) return raw;
  try {
    const url = new URL(raw);
    const hubHost = new URL(HUB_URL).hostname;
    if ((url.protocol === "http:" || url.protocol === "https:") && url.hostname === hubHost) {
      return url.toString();
    }
  } catch {
    // ignore — fallthrough
  }
  return "/auth/login";
}

function errMsg(e: unknown): string {
  if (typeof e === "object" && e && "detail" in e) {
    const d = (e as { detail: unknown }).detail;
    if (typeof d === "object" && d && "message" in d)
      return String((d as { message: unknown }).message);
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return "รูปแบบอีเมลไม่ถูกต้อง";
  }
  return e instanceof Error ? e.message : "ไม่สำเร็จ";
}

function RecoverInner() {
  const params = useSearchParams();
  const returnTo = safeReturnTo(params.get("return_to"));
  const isExternal = returnTo !== "/auth/login";

  const [tab, setTab] = useState<Tab>("backup");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [otp, setOtp] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [doneMsg, setDoneMsg] = useState<string | null>(null);
  const [newCodes, setNewCodes] = useState<string[] | null>(null);

  const reset = () => {
    setError(null);
    setOtp("");
    setOtpSent(false);
  };

  const goLogin = () => {
    window.location.href = returnTo;
  };

  const doBackup = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await recoverWithBackupCode(email, code);
      setDoneMsg(r.message);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const sendOtp = async (regen: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const r = regen
        ? await regenOtpStart(email)
        : await recoverEmailOtpStart(email);
      setOtpSent(true);
      alert(r.message);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const doTotp = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await recoverWithTotp(email, code);
      window.location.href = r.start_url; // → เริ่ม OAuth เชื่อม Gmail ใหม่
    } catch (e) {
      setError(errMsg(e));
      setBusy(false);
    }
  };

  const doTicket = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await submitRecoveryRequest({ email, reason });
      setDoneMsg(r.message);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const verifyOtp = async (regen: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const r = regen
        ? await regenOtpVerify(email, otp)
        : await recoverEmailOtpVerify(email, otp);
      if (r.backup_codes && r.backup_codes.length) setNewCodes(r.backup_codes);
      else setDoneMsg(r.message);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const tabBtn = (t: Tab, label: string) => (
    <button
      onClick={() => {
        setTab(t);
        reset();
      }}
      className={`flex-1 py-2 rounded-md text-xs font-medium transition ${
        tab === t ? "bg-white text-ink-900 shadow-sm" : "text-ink-500"
      }`}
    >
      {label}
    </button>
  );

  return (
    <main className="signal-auth-page min-h-screen grid place-items-center px-4">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-2xl overflow-hidden">
        <div className="px-8 pt-8 pb-6">
          <h1 className="text-xl font-extrabold text-ink-900 mb-1">
            {tab === "regen" ? "ขอ Backup Codes ใหม่" : "กู้บัญชี Passkey"}
          </h1>
          <p className="text-sm text-ink-500 mb-6">
            {tab === "regen"
              ? "codes หาย/ใกล้หมด? ยืนยัน OTP เพื่อรับชุดใหม่ — passkey ยังใช้ได้ปกติ"
              : "ทำอุปกรณ์หาย? ใช้ backup code หรือ email OTP เพื่อลบ Passkey เก่า แล้วตั้งค่าใหม่"}
          </p>

          {newCodes ? (
            <CodesAck
              codes={newCodes}
              onConfirm={goLogin}
              note={
                tab === "regen"
                  ? "Backup codes ชุดใหม่ — passkey ของคุณยังใช้ได้"
                  : "Passkey ถูกลบ + นี่คือ backup codes ชุดใหม่"
              }
            />
          ) : doneMsg ? (
            <div className="space-y-4">
              <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-4 text-sm text-emerald-800">
                ✓ {doneMsg}
              </div>
              <button
                onClick={goLogin}
                className="block text-center w-full py-2.5 rounded-lg bg-ink-900 text-white font-semibold hover:bg-ink-800"
              >
                {isExternal ? "← กลับไปหน้า login ของระบบย่อย" : "ไปหน้า Login"}
              </button>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap gap-1 mb-4 p-1 bg-gray-100 rounded-lg">
                {tabBtn("backup", "Backup Code")}
                {tabBtn("otp", "Email OTP")}
                {tabBtn("totp", "Authenticator")}
                {tabBtn("ticket", "ขอ Admin ช่วย")}
                {tabBtn("regen", "codes ใหม่")}
              </div>

              {(tab === "totp" || tab === "ticket") && (
                <div className="mb-3 text-[11px] text-ink-500 bg-ink-50 border border-ink-100 rounded-lg p-2 leading-relaxed">
                  {tab === "totp"
                    ? "เข้า Gmail เดิม + Passkey ไม่ได้ แต่มีแอป Authenticator → ยืนยันแล้วเปลี่ยนไปบัญชี Google ใหม่"
                    : "ไม่เหลือวิธียืนยันเลย → ยื่นคำขอ ผู้ดูแลจะตรวจบัตร นศ./ปชช. แล้วออกลิงก์ให้"}
                </div>
              )}

              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@uni.ac.th"
                disabled={busy}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg mb-3 focus:ring-2 focus:ring-brand-500"
              />

              {tab === "backup" ? (
                <>
                  <input
                    type="text"
                    value={code}
                    onChange={(e) => setCode(e.target.value.toUpperCase())}
                    placeholder="AB3D-7K9P"
                    disabled={busy}
                    maxLength={20}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg mb-3 font-mono tracking-wider focus:ring-2 focus:ring-brand-500"
                  />
                  <button
                    onClick={doBackup}
                    disabled={busy || !email.trim() || !code.trim()}
                    className="w-full py-2.5 rounded-lg font-semibold bg-brand-600 text-white hover:bg-brand-700 disabled:bg-gray-200 disabled:text-gray-400"
                  >
                    {busy ? "กำลังตรวจสอบ…" : "กู้บัญชีด้วย Backup Code"}
                  </button>
                </>
              ) : tab === "totp" ? (
                <>
                  <input
                    type="text"
                    value={code}
                    onChange={(e) =>
                      setCode(e.target.value.replace(/\D/g, "").slice(0, 6))
                    }
                    placeholder="รหัส 6 หลักจากแอป"
                    inputMode="numeric"
                    disabled={busy}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg mb-3 font-mono tracking-widest text-center focus:ring-2 focus:ring-brand-500"
                  />
                  <button
                    onClick={doTotp}
                    disabled={busy || !email.trim() || code.length !== 6}
                    className="w-full py-2.5 rounded-lg font-semibold bg-brand-600 text-white hover:bg-brand-700 disabled:bg-gray-200 disabled:text-gray-400"
                  >
                    {busy ? "กำลังตรวจสอบ…" : "ยืนยัน → เปลี่ยนบัญชี Google"}
                  </button>
                </>
              ) : tab === "ticket" ? (
                <>
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="อธิบายสั้นๆ ว่าเข้าไม่ได้เพราะอะไร (optional)"
                    disabled={busy}
                    rows={3}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg mb-3 text-sm focus:ring-2 focus:ring-brand-500"
                  />
                  <button
                    onClick={doTicket}
                    disabled={busy || !email.trim()}
                    className="w-full py-2.5 rounded-lg font-semibold bg-brand-600 text-white hover:bg-brand-700 disabled:bg-gray-200 disabled:text-gray-400"
                  >
                    {busy ? "กำลังส่ง…" : "ยื่นคำขอกู้บัญชี"}
                  </button>
                </>
              ) : (
                <>
                  {!otpSent ? (
                    <button
                      onClick={() => sendOtp(tab === "regen")}
                      disabled={busy || !email.trim()}
                      className="w-full py-2.5 rounded-lg font-semibold bg-brand-600 text-white hover:bg-brand-700 disabled:bg-gray-200 disabled:text-gray-400"
                    >
                      {busy ? "กำลังส่ง…" : "ส่ง OTP ทาง Email"}
                    </button>
                  ) : (
                    <>
                      <input
                        type="text"
                        value={otp}
                        onChange={(e) => setOtp(e.target.value)}
                        placeholder="OTP 6 หลัก"
                        disabled={busy}
                        maxLength={6}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg mb-3 font-mono tracking-widest text-center focus:ring-2 focus:ring-brand-500"
                      />
                      <button
                        onClick={() => verifyOtp(tab === "regen")}
                        disabled={busy || !otp.trim()}
                        className="w-full py-2.5 rounded-lg font-semibold bg-brand-600 text-white hover:bg-brand-700 disabled:bg-gray-200 disabled:text-gray-400"
                      >
                        {busy ? "กำลังตรวจสอบ…" : "ยืนยัน OTP"}
                      </button>
                    </>
                  )}
                </>
              )}

              {error && (
                <div className="mt-3 bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-800">
                  {error}
                </div>
              )}

              <a
                href={returnTo}
                className="block text-center text-xs text-ink-400 mt-4 hover:text-ink-600"
              >
                {isExternal ? "← กลับหน้า login ของระบบย่อย" : "← กลับหน้า Login"}
              </a>
            </>
          )}
        </div>
      </div>
    </main>
  );
}

export default function RecoverPage() {
  return (
    <Suspense fallback={null}>
      <RecoverInner />
    </Suspense>
  );
}
