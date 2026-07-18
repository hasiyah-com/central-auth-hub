"use client";

import { useEffect, useState } from "react";
import {
  isPasskeySupported,
  loginWithPasskey,
  loginWithPasskeyDiscoverable,
} from "@/lib/passkey";

const HUB_URL = process.env.NEXT_PUBLIC_HUB_URL || "http://localhost:8000";

export default function LoginPage() {
  const [passkeySupported, setPasskeySupported] = useState<boolean | null>(null);
  const [showPasskeyDialog, setShowPasskeyDialog] = useState(false);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // แจ้งผลจาก flow เปลี่ยนบัญชี Google (redirect กลับมาที่หน้า login)
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; text: string } | null>(
    null
  );
  // Global auth-policy — admin อาจปิด Google หรือ Passkey
  const [policy, setPolicy] = useState<{ google: boolean; passkey: boolean }>({
    google: true,
    passkey: true,
  });

  useEffect(() => {
    // อ่านผล change-google จาก query (redirect กลับมาแบบ full-page — ไม่ใช้ useSearchParams
    // เลี่ยง Suspense boundary requirement)
    const q = new URLSearchParams(window.location.search);
    if (q.get("google_changed") === "1") {
      setNotice({
        kind: "ok",
        text: "เปลี่ยนบัญชี Google สำเร็จ — เข้าสู่ระบบด้วยบัญชีใหม่",
      });
    } else if ((q.get("error") || "").startsWith("change_google")) {
      setNotice({
        kind: "err",
        text: "เปลี่ยนบัญชี Google ไม่สำเร็จ — ลิงก์อาจหมดอายุ หรือบัญชีนั้นถูกใช้แล้ว กรุณาลองใหม่",
      });
    }
  }, []);

  useEffect(() => {
    setPasskeySupported(isPasskeySupported());
    // อ่าน policy ผ่าน Next rewrite (/api/hub → backend) — ไม่มี CORS
    fetch("/api/hub/auth/policy")
      .then((r) => (r.ok ? r.json() : null))
      .then((p) => {
        if (p && typeof p.google === "boolean" && typeof p.passkey === "boolean") {
          setPolicy(p);
        }
      })
      .catch(() => {
        /* fail-safe: คงค่า default (เปิดทั้งคู่) */
      });
  }, []);

  const persistAndRedirect = async (token: string, isAdmin: boolean) => {
    const setRes = await fetch("/api/set-token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ token }),
    });
    if (!setRes.ok) {
      const body = await setRes.json().catch(() => ({}));
      throw new Error(body.error || "ไม่สามารถบันทึก session ได้");
    }
    window.location.href = isAdmin ? "/dashboard" : "/developer/subsystems";
  };

  const friendlyErr = (e: unknown): string => {
    const msg =
      e instanceof Error
        ? e.message
        : typeof e === "object" && e && "detail" in e
          ? String((e as { detail: unknown }).detail)
          : "ไม่สามารถเข้าสู่ระบบได้ กรุณาลองใหม่อีกครั้ง";
    // OWASP anti-enumeration: auth-failure ทุกกรณีใช้ข้อความเดียวกัน (generic)
    // — ไม่บอกว่า email มี/ไม่มี passkey หรือ credential ผิด
    if (
      msg.includes("invalid_credential") ||
      msg.includes("assertion_verify_failed")
    )
      return "ไม่สามารถเข้าสู่ระบบได้ กรุณาลองใหม่อีกครั้ง";
    if (msg.includes("challenge_expired")) return "Session หมดอายุ กรุณาลองใหม่";
    return msg;
  };

  const handlePasskeyLogin = async () => {
    if (!email.trim()) {
      setError("กรุณากรอก email");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const result = await loginWithPasskey(email.trim());
      await persistAndRedirect(result.access_token, result.user.is_hub_admin);
    } catch (e) {
      setError(friendlyErr(e));
      setBusy(false);
    }
  };

  const handleDiscoverable = async () => {
    setError(null);
    setBusy(true);
    try {
      const result = await loginWithPasskeyDiscoverable();
      await persistAndRedirect(result.access_token, result.user.is_hub_admin);
    } catch (e) {
      setError(friendlyErr(e));
      setBusy(false);
    }
  };

  return (
    <main className="min-h-screen grid place-items-center bg-gradient-to-br from-ink-900 via-ink-800 to-brand-900 px-4">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-2xl overflow-hidden">
        <div className="px-8 pt-10 pb-8">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-brand-600 to-brand-900 grid place-items-center text-white text-xl font-bold">
              H
            </div>
            <div>
              <div className="text-xs text-ink-500 font-semibold uppercase tracking-wider">
                Central Auth Hub
              </div>
              <div className="text-lg font-bold text-ink-900">Admin Console</div>
            </div>
          </div>

          <h1 className="text-2xl font-extrabold text-ink-900 mb-2">
            เข้าสู่ระบบ
          </h1>
          <p className="text-sm text-ink-500 mb-8">
            สำหรับผู้ดูแลระบบ — ใช้ Passkey หรือบัญชี Google ที่ลงทะเบียนไว้
          </p>

          {notice && (
            <div
              className={
                "mb-6 p-3 rounded-xl text-sm border " +
                (notice.kind === "ok"
                  ? "bg-emerald-50 border-emerald-200 text-emerald-800"
                  : "bg-rose-50 border-rose-200 text-rose-800")
              }
            >
              {notice.kind === "ok" ? "✓ " : "⚠ "}
              {notice.text}
            </div>
          )}

          {/* Passkey login (Phase 2) — conditional on browser support + policy */}
          {policy.passkey && passkeySupported && !showPasskeyDialog && (
            <button
              onClick={() => setShowPasskeyDialog(true)}
              className="w-full flex items-center justify-center gap-3 px-4 py-3 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold transition mb-3"
            >
              <span className="text-xl">🔑</span>
              <span>Sign in with Passkey</span>
            </button>
          )}

          {/* Passkey email-first dialog */}
          {policy.passkey && showPasskeyDialog && (
            <div className="mb-3 p-4 rounded-xl border-2 border-emerald-200 bg-emerald-50 space-y-3">
              <div className="flex items-center justify-between">
                <div className="font-semibold text-emerald-900">
                  🔑 Sign in with Passkey
                </div>
                <button
                  onClick={() => {
                    setShowPasskeyDialog(false);
                    setError(null);
                    setEmail("");
                  }}
                  disabled={busy}
                  className="text-emerald-700 hover:text-emerald-900 text-sm"
                >
                  ยกเลิก
                </button>
              </div>
              <p className="text-xs text-emerald-800">
                กรอก email ของคุณ แล้วระบบจะถาม biometric / security key
              </p>
              <input
                type="email"
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@uni.ac.th"
                disabled={busy}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !busy) handlePasskeyLogin();
                }}
                className="w-full px-3 py-2 border border-emerald-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 bg-white"
              />
              {error && (
                <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2">
                  {error}
                </div>
              )}
              <button
                onClick={handlePasskeyLogin}
                disabled={busy || !email.trim()}
                className={`w-full py-2.5 rounded-lg font-semibold transition ${
                  busy || !email.trim()
                    ? "bg-emerald-300 text-white cursor-not-allowed"
                    : "bg-emerald-600 text-white hover:bg-emerald-700"
                }`}
              >
                {busy ? "กำลังตรวจ Passkey…" : "ดำเนินการต่อ"}
              </button>
              <div className="flex items-center gap-2 text-[10px] text-emerald-700">
                <span className="flex-1 h-px bg-emerald-200" />
                หรือ
                <span className="flex-1 h-px bg-emerald-200" />
              </div>
              <button
                onClick={handleDiscoverable}
                disabled={busy}
                className="w-full py-2 rounded-lg text-sm font-medium text-emerald-700 hover:bg-emerald-100 border border-emerald-200 transition disabled:opacity-50"
              >
                🔓 เข้าโดยไม่กรอก email (เลือก passkey จากอุปกรณ์)
              </button>
            </div>
          )}

          {policy.passkey && policy.google && passkeySupported === false && (
            <div className="mb-3 p-3 text-xs text-amber-900 bg-amber-50 border border-amber-200 rounded-lg">
              ⚠️ เบราว์เซอร์นี้ไม่รองรับ Passkey — กรุณาใช้ Google login แทน
            </div>
          )}

          {/* Passkey ปิด + browser ไม่รองรับ → เตือนว่าใช้ไม่ได้ */}
          {!policy.google && policy.passkey && passkeySupported === false && (
            <div className="mb-3 p-3 text-xs text-rose-900 bg-rose-50 border border-rose-200 rounded-lg">
              ⚠️ เบราว์เซอร์นี้ไม่รองรับ Passkey และผู้ดูแลปิด Google login —
              กรุณาใช้เบราว์เซอร์ที่รองรับ Passkey
            </div>
          )}

          {/* Google login — fallback ทุก browser (เคารพ policy) */}
          {policy.google && (
          <a
            href={`${HUB_URL}/auth/google/login`}
            className="w-full flex items-center justify-center gap-3 px-4 py-3 rounded-xl bg-ink-900 hover:bg-ink-800 text-white font-semibold transition"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path
                d="M21.6 12.227c0-.709-.064-1.39-.182-2.045H12v3.868h5.382a4.6 4.6 0 0 1-1.996 3.018v2.51h3.232c1.891-1.742 2.982-4.305 2.982-7.35Z"
                fill="#4285F4"
              />
              <path
                d="M12 22c2.7 0 4.964-.895 6.618-2.423l-3.232-2.509c-.895.6-2.04.955-3.386.955-2.605 0-4.81-1.76-5.595-4.123H3.064v2.59A9.996 9.996 0 0 0 12 22Z"
                fill="#34A853"
              />
              <path
                d="M6.405 13.9a6.003 6.003 0 0 1 0-3.8V7.51H3.064a9.996 9.996 0 0 0 0 8.98l3.341-2.59Z"
                fill="#FBBC05"
              />
              <path
                d="M12 5.977c1.468 0 2.786.505 3.823 1.496l2.868-2.868C16.96 2.99 14.695 2 12 2A9.996 9.996 0 0 0 3.064 7.51l3.341 2.59C7.19 7.736 9.395 5.977 12 5.977Z"
                fill="#EA4335"
              />
            </svg>
            <span>Sign in with Google</span>
          </a>
          )}

          {/* LINE login — ปิดชั่วคราว (Q3 decision 2026-06-10)
              email scope ยังแก้ไม่ตก, code อยู่ใน git/backend จะกลับมาเมื่อแก้ได้

          <a href={`${HUB_URL}/auth/line/login`} className="mt-3 ...">
            Sign in with LINE
          </a>
          */}

          <div className="mt-6 text-xs text-ink-400 text-center">
            เฉพาะผู้ใช้ที่มีสิทธิ์ <code className="font-mono">is_hub_admin</code> เท่านั้น
          </div>
          {policy.passkey && passkeySupported && (
            <div className="mt-2 text-center">
              <a
                href="/auth/passkey/recover"
                className="text-xs text-emerald-600 hover:text-emerald-700"
              >
                ทำ Passkey หาย? กู้บัญชี
              </a>
            </div>
          )}
        </div>

        <div className="px-8 py-5 bg-ink-50 border-t border-ink-100">
          <div className="text-xs text-ink-500 flex items-center justify-between">
            <span>OAuth 2.0 · PKCE · JWT RS256 · WebAuthn</span>
            <span className="font-mono">v0.5.0</span>
          </div>
        </div>
      </div>
    </main>
  );
}
