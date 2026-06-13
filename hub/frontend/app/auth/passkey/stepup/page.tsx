"use client";

/**
 * Step-up re-auth (Phase 5) — ยืนยันตัวตนก่อนทำ critical action.
 * ลอง passkey ก่อน → ไม่มี/ไม่รองรับ → fallback email OTP.
 * สำเร็จ → trusted session 15 นาที → กลับ return_to.
 */

import { Suspense, useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import {
  isPasskeySupported,
  stepUpWithPasskey,
  stepupOtpStart,
  stepupOtpVerify,
} from "@/lib/passkey";

function errMsg(e: unknown): string {
  if (typeof e === "object" && e && "detail" in e) {
    const d = (e as { detail: unknown }).detail;
    if (typeof d === "object" && d && "message" in d)
      return String((d as { message: unknown }).message);
    if (typeof d === "string") return d;
  }
  return e instanceof Error ? e.message : "ยืนยันไม่สำเร็จ";
}

function hasCode(e: unknown, code: string): boolean {
  return (
    typeof e === "object" &&
    e !== null &&
    "detail" in e &&
    typeof (e as { detail: unknown }).detail === "object" &&
    ((e as { detail: { code?: string } }).detail?.code === code)
  );
}

function StepupInner() {
  const params = useSearchParams();
  const returnTo = params.get("return_to") || "/dashboard";
  const [supported, setSupported] = useState(true); // optimistic — กัน flash disabled
  const [mode, setMode] = useState<"passkey" | "otp">("passkey");
  const [otpSent, setOtpSent] = useState(false);
  const [otp, setOtp] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // เช็ค browser support ฝั่ง client (เลี่ยง hydration mismatch — call ใน effect)
  useEffect(() => {
    const ok = isPasskeySupported();
    setSupported(ok);
    if (!ok) setMode("otp"); // ไม่รองรับ passkey → ใช้ OTP เลย
  }, []);

  const goBack = () => {
    window.location.href = returnTo;
  };

  const doPasskey = async () => {
    setBusy(true);
    setError(null);
    try {
      await stepUpWithPasskey();
      goBack();
    } catch (e) {
      if (hasCode(e, "no_passkey")) {
        setMode("otp");
        setError("คุณยังไม่มี Passkey — ใช้ OTP ทาง email แทน");
      } else {
        setError(errMsg(e));
      }
      setBusy(false);
    }
  };

  const doOtpSend = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await stepupOtpStart();
      setOtpSent(true);
      setError(null);
      alert(r.message);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const doOtpVerify = async () => {
    setBusy(true);
    setError(null);
    try {
      await stepupOtpVerify(otp);
      goBack();
    } catch (e) {
      setError(errMsg(e));
      setBusy(false);
    }
  };

  return (
    <main className="min-h-screen grid place-items-center bg-gradient-to-br from-ink-900 via-ink-800 to-brand-900 px-4">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-2xl overflow-hidden">
        <div className="px-8 pt-8 pb-6">
          <div className="text-4xl mb-3">🔐</div>
          <h1 className="text-xl font-extrabold text-ink-900 mb-1">
            ยืนยันตัวตนอีกครั้ง
          </h1>
          <p className="text-sm text-ink-500 mb-6">
            การกระทำนี้สำคัญ — ต้องยืนยันตัวตนก่อน (มีผล 15 นาที)
          </p>

          {error && (
            <div className="mb-4 bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
              {error}
            </div>
          )}

          {mode === "passkey" ? (
            <div className="space-y-3">
              <button
                onClick={doPasskey}
                disabled={busy || !supported}
                className="w-full py-3 rounded-xl font-semibold bg-emerald-600 text-white hover:bg-emerald-700 disabled:bg-gray-200 disabled:text-gray-400"
              >
                {busy ? "กำลังยืนยัน…" : "🔑 ยืนยันด้วย Passkey"}
              </button>
              <button
                onClick={() => setMode("otp")}
                disabled={busy}
                className="w-full py-2 text-sm text-ink-500 hover:text-ink-700"
              >
                ใช้ OTP ทาง email แทน
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              {!otpSent ? (
                <button
                  onClick={doOtpSend}
                  disabled={busy}
                  className="w-full py-3 rounded-xl font-semibold bg-brand-600 text-white hover:bg-brand-700 disabled:bg-gray-200 disabled:text-gray-400"
                >
                  {busy ? "กำลังส่ง…" : "📧 ส่ง OTP ทาง Email"}
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
                    autoFocus
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && otp.trim()) doOtpVerify();
                    }}
                    className="w-full px-3 py-2.5 border border-gray-300 rounded-lg font-mono tracking-widest text-center focus:ring-2 focus:ring-brand-500"
                  />
                  <button
                    onClick={doOtpVerify}
                    disabled={busy || !otp.trim()}
                    className="w-full py-3 rounded-xl font-semibold bg-brand-600 text-white hover:bg-brand-700 disabled:bg-gray-200 disabled:text-gray-400"
                  >
                    {busy ? "กำลังตรวจสอบ…" : "ยืนยัน OTP"}
                  </button>
                </>
              )}
              {supported && (
                <button
                  onClick={() => {
                    setMode("passkey");
                    setError(null);
                  }}
                  disabled={busy}
                  className="w-full py-2 text-sm text-ink-500 hover:text-ink-700"
                >
                  ← กลับไปใช้ Passkey
                </button>
              )}
            </div>
          )}

          <button
            onClick={goBack}
            className="block w-full text-center text-xs text-ink-400 mt-5 hover:text-ink-600"
          >
            ยกเลิก — กลับหน้าเดิม
          </button>
        </div>
      </div>
    </main>
  );
}

export default function StepupPage() {
  return (
    <Suspense>
      <StepupInner />
    </Suspense>
  );
}
