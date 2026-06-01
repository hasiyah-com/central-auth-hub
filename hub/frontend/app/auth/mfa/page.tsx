"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

type ChallengeMeta = {
  challenge_id: string;
  method: string;
  email_masked: string;
  expires_at: string; // ISO UTC
  attempts: number;
  max_attempts: number;
  used: boolean;
  expired: boolean;
};

type VerifyResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: { id: string; email: string; full_name: string; user_type: string };
};

const HUB_URL =
  process.env.NEXT_PUBLIC_HUB_URL || "http://localhost:8000";

export default function MfaPage() {
  const router = useRouter();
  const params = useSearchParams();
  const challengeId = params.get("challenge") || "";

  const [meta, setMeta] = useState<ChallengeMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [resending, setResending] = useState(false);
  const [resentMsg, setResentMsg] = useState<string | null>(null);

  const [digits, setDigits] = useState<string[]>(["", "", "", "", "", ""]);
  const inputs = useRef<Array<HTMLInputElement | null>>([]);

  const [secondsLeft, setSecondsLeft] = useState<number>(0);

  // ─── 1) Fetch challenge meta on mount ──────────────────
  useEffect(() => {
    if (!challengeId) {
      setError("ไม่พบ challenge — กรุณา login ใหม่");
      return;
    }
    fetch(`${HUB_URL}/mfa/challenge/${challengeId}`)
      .then(async (r) => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(body.detail || `Status ${r.status}`);
        }
        return r.json();
      })
      .then((m: ChallengeMeta) => {
        setMeta(m);
        if (m.expired) setError("OTP หมดอายุแล้ว — login ใหม่");
        if (m.used) setError("OTP นี้ถูกใช้แล้ว — login ใหม่");
      })
      .catch((e) => setError(e.message || "โหลด challenge ไม่สำเร็จ"));
  }, [challengeId]);

  // ─── 2) Countdown ───────────────────────────────────────
  useEffect(() => {
    if (!meta) return;
    const tick = () => {
      const remain = Math.max(
        0,
        Math.floor((new Date(meta.expires_at).getTime() - Date.now()) / 1000)
      );
      setSecondsLeft(remain);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [meta]);

  // ─── 3) Input handlers ──────────────────────────────────
  function setDigit(idx: number, v: string) {
    const cleaned = v.replace(/\D/g, "").slice(0, 1);
    setDigits((d) => {
      const next = [...d];
      next[idx] = cleaned;
      return next;
    });
    if (cleaned && idx < 5) {
      inputs.current[idx + 1]?.focus();
    }
  }

  function handleKeyDown(idx: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && !digits[idx] && idx > 0) {
      inputs.current[idx - 1]?.focus();
    }
  }

  function handlePaste(e: React.ClipboardEvent<HTMLInputElement>) {
    const text = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6);
    if (text.length >= 1) {
      e.preventDefault();
      const arr = text.padEnd(6, " ").split("").map((c) => (c === " " ? "" : c));
      setDigits(arr);
      const lastFilled = Math.min(text.length, 5);
      inputs.current[lastFilled]?.focus();
    }
  }

  // ─── 4) Verify ──────────────────────────────────────────
  const verify = useCallback(
    async (otp: string) => {
      if (!challengeId) return;
      setSubmitting(true);
      setError(null);
      try {
        const r = await fetch(`${HUB_URL}/mfa/verify`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ challenge_id: challengeId, otp }),
        });
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(body.detail || `Status ${r.status}`);
        }
        const data: VerifyResponse = await r.json();
        // ตั้ง cookie ผ่าน /api/set-token แล้ว redirect ตาม role
        const res = await fetch("/api/set-token", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ token: data.access_token }),
        });
        if (!res.ok) {
          throw new Error("set-token failed");
        }
        const me = await fetch("/api/me", { credentials: "include" })
          .then((rr) => (rr.ok ? rr.json() : null))
          .catch(() => null);
        const isAdmin =
          me?.is_hub_admin === true || me?.user_type === "admin";
        window.location.href = isAdmin ? "/dashboard" : "/developer/subsystems";
      } catch (e) {
        const err = e as { message?: string };
        setError(err.message || "ยืนยันไม่สำเร็จ");
        setDigits(["", "", "", "", "", ""]);
        inputs.current[0]?.focus();
      } finally {
        setSubmitting(false);
      }
    },
    [challengeId, router]
  );

  // Auto-submit เมื่อกรอกครบ 6 หลัก
  useEffect(() => {
    if (digits.every((d) => d.length === 1) && !submitting) {
      verify(digits.join(""));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [digits]);

  async function resend() {
    if (!challengeId || resending) return;
    setResending(true);
    setResentMsg(null);
    setError(null);
    try {
      const r = await fetch(`${HUB_URL}/mfa/resend`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ challenge_id: challengeId }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({}));
        throw new Error(body.detail || `Status ${r.status}`);
      }
      const data = await r.json();
      setMeta((m) => (m ? { ...m, expires_at: data.expires_at } : m));
      setResentMsg("ส่ง OTP ใหม่แล้ว — ตรวจ inbox");
      setDigits(["", "", "", "", "", ""]);
      inputs.current[0]?.focus();
    } catch (e) {
      const err = e as { message?: string };
      setError(err.message || "ส่งใหม่ไม่สำเร็จ");
    } finally {
      setResending(false);
    }
  }

  const mins = Math.floor(secondsLeft / 60);
  const secs = secondsLeft % 60;
  const timerColor =
    secondsLeft <= 30 ? "text-rose-600" : secondsLeft <= 60 ? "text-amber-600" : "text-ink-600";

  return (
    <main className="min-h-screen grid place-items-center bg-gradient-to-br from-ink-900 via-brand-900 to-ink-900 p-6">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-xl p-8">
        <div className="mb-6">
          <div className="text-[10px] font-bold uppercase tracking-widest text-brand-600 mb-2">
            🛡️ Multi-Factor Authentication
          </div>
          <h1 className="text-2xl font-extrabold text-ink-900">ยืนยันตัวตน</h1>
          {meta && (
            <p className="text-sm text-ink-500 mt-2">
              เราส่งรหัส 6 หลักไปที่ <strong>{meta.email_masked}</strong>
            </p>
          )}
        </div>

        {/* OTP Input — 6 ช่อง */}
        <div className="flex gap-2 justify-center mb-4" onPaste={handlePaste}>
          {digits.map((d, i) => (
            <input
              key={i}
              ref={(el) => {
                inputs.current[i] = el;
              }}
              type="text"
              inputMode="numeric"
              maxLength={1}
              value={d}
              onChange={(e) => setDigit(i, e.target.value)}
              onKeyDown={(e) => handleKeyDown(i, e)}
              disabled={submitting}
              className="w-12 h-14 text-center text-2xl font-bold font-mono border-2 border-ink-200 rounded-lg focus:outline-none focus:border-brand-500 disabled:opacity-50"
            />
          ))}
        </div>

        {/* Countdown */}
        {meta && secondsLeft > 0 && (
          <div className={`text-center text-sm font-medium mb-3 ${timerColor}`}>
            หมดอายุใน {mins}:{secs.toString().padStart(2, "0")}
          </div>
        )}
        {meta && secondsLeft === 0 && (
          <div className="text-center text-sm font-medium mb-3 text-rose-600">
            ⌛ OTP หมดอายุแล้ว — กดส่งใหม่
          </div>
        )}

        {/* Status messages */}
        {error && (
          <div className="mb-3 p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm">
            {error}
          </div>
        )}
        {resentMsg && !error && (
          <div className="mb-3 p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-700 text-sm">
            {resentMsg}
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center justify-between text-sm">
          <button
            onClick={resend}
            disabled={resending || !meta}
            className="text-brand-600 hover:text-brand-700 font-medium disabled:opacity-50"
          >
            {resending ? "กำลังส่ง..." : "ส่ง OTP ใหม่"}
          </button>
          <a
            href="/auth/login"
            className="text-ink-500 hover:text-ink-700 font-medium"
          >
            ← Login ใหม่
          </a>
        </div>

        {meta && (
          <div className="mt-6 pt-4 border-t border-ink-100 text-[11px] text-ink-400 text-center">
            ใส่ผิด {meta.attempts}/{meta.max_attempts} ครั้ง — {meta.method.toUpperCase()} method
          </div>
        )}
      </div>
    </main>
  );
}
