"use client";

// useSearchParams() ต้อง render ตอน request time — กัน prerender error ตอน next build
export const dynamic = "force-dynamic";

/**
 * หน้า interstitial "เพิ่มความปลอดภัยให้บัญชี" — แสดง **ครั้งเดียวหลัง login**
 * สำหรับ user ที่ยังไม่มี factor (should_prompt_setup) ก่อนเข้าหน้าหลัก.
 *
 * แทนที่ banner เดิมที่ขึ้นทุกหน้า — auth/callback จะพามาที่นี่เมื่อ should_prompt_setup
 * แล้วค่อยไปหน้าหลัก. เลือกวิธี → ไปหน้า account ตั้งค่าจริง; "ไว้ทีหลัง" = snooze 7 วัน;
 * "ไม่ต้องถามอีก" = ปิดถาวร. ทั้ง 3 ทางออกไป `next` (หน้าหลักตาม role).
 */

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  fetchSecurityStatus,
  dismissSecurityOnboarding,
  snoozeSecurityOnboarding,
} from "@/lib/passkey";

function SetupInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [ready, setReady] = useState(false);
  const [accountHref, setAccountHref] = useState("/account");
  const [dest, setDest] = useState("/dashboard");

  useEffect(() => {
    (async () => {
      // role → หน้าหลัก + account href
      const me = await fetch("/api/me", { credentials: "include" })
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null);
      const isAdmin = me?.is_hub_admin === true || me?.user_type === "admin";
      const home = isAdmin ? "/dashboard" : "/developer/subsystems";
      const acct = isAdmin ? "/account" : "/developer/account";
      const next = params.get("next") || home;
      setAccountHref(acct);
      setDest(next);

      // ถ้าไม่ควร prompt แล้ว (มี factor / ปิดถาวร / อยู่ใน snooze) → ข้ามไปหน้าหลักเลย
      const status = await fetchSecurityStatus().catch(() => null);
      if (!status || !status.should_prompt_setup) {
        window.location.href = next;
        return;
      }
      setReady(true);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const go = (setup: "passkey" | "totp" | "both") =>
    router.push(`${accountHref}?setup=${setup}`);

  const later = async () => {
    try {
      await snoozeSecurityOnboarding(); // พัก 7 วัน (ผูกกับบัญชี)
    } catch {
      /* fail-safe */
    }
    window.location.href = dest;
  };

  const never = async () => {
    try {
      await dismissSecurityOnboarding();
    } catch {
      /* fail-safe */
    }
    window.location.href = dest;
  };

  if (!ready) {
    return (
      <main className="min-h-screen grid place-items-center bg-ink-50">
        <div className="flex items-center gap-3 text-ink-500">
          <div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
          <span>กำลังเข้าสู่ระบบ…</span>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen grid place-items-center bg-ink-50 p-4">
      <div className="w-full max-w-2xl rounded-2xl border border-brand-200 bg-gradient-to-br from-brand-50 to-white p-6 shadow-sm sm:p-8">
        <div className="flex items-start gap-3">
          <span className="text-3xl shrink-0">🛡️</span>
          <div className="min-w-0 flex-1">
            <h1 className="text-lg font-bold text-ink-900">
              เพิ่มความปลอดภัยให้บัญชี
            </h1>
            <p className="mt-1 text-sm text-ink-500">
              เลือกวิธียืนยันตัวตนที่จะใช้ — ป้องกันบัญชีแม้รหัส Google หลุด
            </p>

            <div className="mt-5 grid gap-2 sm:grid-cols-3">
              <button
                onClick={() => go("passkey")}
                className="group flex flex-col items-start gap-1 rounded-xl border border-gray-200 bg-white p-3 text-left transition hover:border-brand-400 hover:shadow"
              >
                <span className="flex items-center gap-1.5 text-sm font-semibold text-ink-900">
                  🔑 Passkey
                  <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-bold text-emerald-700">
                    แนะนำ
                  </span>
                </span>
                <span className="text-xs text-ink-400">
                  ลายนิ้วมือ/Face/PIN — แข็งแรงสุด กัน phishing
                </span>
              </button>

              <button
                onClick={() => go("totp")}
                className="flex flex-col items-start gap-1 rounded-xl border border-gray-200 bg-white p-3 text-left transition hover:border-brand-400 hover:shadow"
              >
                <span className="text-sm font-semibold text-ink-900">
                  📱 Authenticator
                </span>
                <span className="text-xs text-ink-400">
                  รหัส 6 หลักจากแอป — ใช้ได้ทุกอุปกรณ์
                </span>
              </button>

              <button
                onClick={() => go("both")}
                className="flex flex-col items-start gap-1 rounded-xl border border-gray-200 bg-white p-3 text-left transition hover:border-brand-400 hover:shadow"
              >
                <span className="flex items-center gap-1.5 text-sm font-semibold text-ink-900">
                  ✨ ทั้งสอง
                  <span className="rounded bg-brand-100 px-1.5 py-0.5 text-[10px] font-bold text-brand-700">
                    ปลอดภัยสุด
                  </span>
                </span>
                <span className="text-xs text-ink-400">
                  Passkey หลัก + TOTP กู้บัญชี
                </span>
              </button>
            </div>

            <div className="mt-5 flex items-center gap-4">
              <button
                onClick={later}
                className="text-sm text-ink-400 hover:text-ink-600"
              >
                ไว้ทีหลัง
              </button>
              <button
                onClick={never}
                className="text-sm text-ink-400 hover:text-ink-600"
              >
                ไม่ต้องถามอีก
              </button>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}

export default function SetupPage() {
  return (
    <Suspense fallback={null}>
      <SetupInner />
    </Suspense>
  );
}
