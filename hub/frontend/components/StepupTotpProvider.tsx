"use client";

/**
 * Global fallback modal สำหรับ inline step-up ด้วย TOTP.
 *
 * mount ครั้งเดียวใน root layout → ลงทะเบียน prompt กับ `runWithStepup` (lib/passkey.ts).
 * เมื่อ critical action เจอ 403 stepup_required แล้ว passkey ไม่ได้ (ไม่มี passkey /
 * user กด cancel) → `runWithStepup` เรียก prompt นี้ → เด้ง modal กรอกรหัส 6 หลัก.
 *
 * modal จัดการ verify + error เอง แล้ว resolve:
 *   - true  → ยืนยัน TOTP สำเร็จ (stepup cache method="totp" ถูก set) → caller retry ต่อ
 *   - false → user ปิด modal → caller คืน error เดิม (เช่น no_passkey)
 *
 * ถ้า user ไม่มี TOTP (enabled=false) → แสดงข้อความแนะนำแทนช่องกรอก (เลี่ยง dead-end).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  registerTotpStepupPrompt,
  stepupWithTotp,
  totpStatus,
} from "@/lib/passkey";

type Resolver = (ok: boolean) => void;

export default function StepupTotpProvider({
  children,
}: {
  children?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [checking, setChecking] = useState(true);
  const [enabled, setEnabled] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const resolverRef = useRef<Resolver | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const finish = useCallback((ok: boolean) => {
    const resolve = resolverRef.current;
    resolverRef.current = null;
    setOpen(false);
    setCode("");
    setError(null);
    setBusy(false);
    resolve?.(ok);
  }, []);

  // ลงทะเบียน prompt กับ runWithStepup — เปิด modal + คืน Promise<boolean>
  useEffect(() => {
    registerTotpStepupPrompt(
      () =>
        new Promise<boolean>((resolve) => {
          resolverRef.current = resolve;
          setCode("");
          setError(null);
          setBusy(false);
          setChecking(true);
          setEnabled(false);
          setOpen(true);
          // เช็คว่ามี TOTP active ไหม (เลี่ยง dead-end ถ้าไม่มี)
          totpStatus()
            .then((s) => setEnabled(s.enabled))
            .catch(() => setEnabled(false))
            .finally(() => setChecking(false));
        })
    );
    return () => registerTotpStepupPrompt(null);
  }, []);

  // autofocus ช่องกรอกเมื่อพร้อม
  useEffect(() => {
    if (open && enabled && !checking) inputRef.current?.focus();
  }, [open, enabled, checking]);

  const submit = useCallback(async () => {
    const c = code.trim();
    if (c.length < 6 || busy) return;
    setBusy(true);
    setError(null);
    try {
      await stepupWithTotp(c);
      finish(true); // สำเร็จ → cache method="totp" แล้ว
    } catch (e) {
      const detail = (e as { detail?: unknown })?.detail;
      const msg =
        typeof detail === "object" && detail && "message" in detail
          ? String((detail as { message: unknown }).message)
          : "รหัสไม่ถูกต้อง — ลองอีกครั้ง";
      setError(msg);
      setCode("");
      setBusy(false);
      inputRef.current?.focus();
    }
  }, [code, busy, finish]);

  return (
    <>
      {children}
      {open && (
        <div
          className="fixed inset-0 z-[100] grid place-items-center bg-black/50 px-4"
          role="dialog"
          aria-modal="true"
          onKeyDown={(e) => {
            if (e.key === "Escape") finish(false);
          }}
        >
          <div className="w-full max-w-sm rounded-2xl bg-white shadow-2xl overflow-hidden">
            <div className="px-7 pt-7 pb-6">
              <div className="text-3xl mb-2">🔐</div>
              <h2 className="text-lg font-extrabold text-ink-900 mb-1">
                ยืนยันด้วย Authenticator
              </h2>
              <p className="text-sm text-ink-500 mb-5">
                กรอกรหัส 6 หลักจากแอป Authenticator เพื่อยืนยันการกระทำนี้
                (มีผล 15 นาที)
              </p>

              {error && (
                <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                  {error}
                </div>
              )}

              {checking ? (
                <div className="py-4 text-center text-sm text-ink-400">
                  กำลังตรวจสอบ…
                </div>
              ) : enabled ? (
                <div className="space-y-3">
                  <input
                    ref={inputRef}
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    value={code}
                    onChange={(e) =>
                      setCode(e.target.value.replace(/\D/g, "").slice(0, 6))
                    }
                    placeholder="123456"
                    disabled={busy}
                    maxLength={6}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") submit();
                    }}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-center font-mono text-lg tracking-[0.5em] focus:ring-2 focus:ring-brand-500"
                  />
                  <button
                    onClick={submit}
                    disabled={busy || code.trim().length < 6}
                    className="w-full rounded-xl bg-emerald-600 py-3 font-semibold text-white hover:bg-emerald-700 disabled:bg-gray-200 disabled:text-gray-400"
                  >
                    {busy ? "กำลังตรวจสอบ…" : "ยืนยัน"}
                  </button>
                </div>
              ) : (
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                  คุณยังไม่มี Passkey หรือ Authenticator ที่ใช้ได้ —
                  ตั้งค่าที่หน้าบัญชี หรือใช้ Account Recovery
                </div>
              )}

              <button
                onClick={() => finish(false)}
                disabled={busy}
                className="mt-4 block w-full text-center text-xs text-ink-400 hover:text-ink-600"
              >
                ยกเลิก
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
