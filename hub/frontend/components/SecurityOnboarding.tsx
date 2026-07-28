"use client";

/**
 * SecurityOnboarding — การ์ดชวนตั้งค่ายืนยันตัวตนหลัง login (เฉพาะ user ที่ยังไม่มี factor).
 *
 * แทน PasskeyNudgeBanner เดิม — เป็น superset: เสนอ Passkey / Authenticator (TOTP) /
 * ทั้งสอง. แสดงเมื่อ `!has_second_factor && !security_onboarding_dismissed`
 * (มี passkey หรือ TOTP แล้ว → ไม่กวน).
 *
 * เลือกแล้ว → นำไปหน้า /account?setup=... (ที่ตั้งค่าจริง — reuse UI enroll เดิม,
 * WebAuthn/QR ต้องการ user gesture ในหน้านั้น). "ไว้ทีหลัง" = ปิด session นี้
 * (sessionStorage); "ไม่ต้องถามอีก" = ปิดถาวร (backend flag).
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  fetchSecurityStatus,
  dismissSecurityOnboarding,
  snoozeSecurityOnboarding,
  type SecurityStatus,
} from "@/lib/passkey";

export function SecurityOnboarding({
  accountHref = "/account",
}: {
  accountHref?: string;
}) {
  const router = useRouter();
  const [status, setStatus] = useState<SecurityStatus | null>(null);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    fetchSecurityStatus()
      .then(setStatus)
      .catch(() => setStatus(null)); // fail-safe — เงียบถ้าเรียกไม่สำเร็จ
  }, []);

  if (hidden || !status) return null;
  // should_prompt_setup = source of truth เดียวกับ OAuth interstitial
  // (ไม่มี factor + ไม่ได้กด "ไม่ถามอีก" + ไม่อยู่ในช่วง snooze 7 วัน)
  if (!status.should_prompt_setup) return null;

  const go = (setup: "passkey" | "totp" | "both") =>
    router.push(`${accountHref}?setup=${setup}`);

  const later = async () => {
    setHidden(true);
    try {
      await snoozeSecurityOnboarding(); // พัก 7 วัน ผูกกับบัญชี ไม่ใช่แค่เครื่องนี้
    } catch {
      /* fail-safe — ปิด UI แล้ว แม้ save ไม่สำเร็จ */
    }
  };

  const never = async () => {
    setHidden(true);
    try {
      await dismissSecurityOnboarding();
    } catch {
      /* fail-safe — ปิด UI แล้ว แม้ save flag ไม่สำเร็จ */
    }
  };

  return (
    <div className="mx-8 mt-4 rounded-2xl border border-brand-200 bg-gradient-to-br from-brand-50 to-white p-5 shadow-sm">
      <div className="flex items-start gap-3">
        <span className="text-2xl shrink-0">🛡️</span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-bold text-ink-900">
            เพิ่มความปลอดภัยให้บัญชี
          </h3>
          <p className="mt-0.5 text-sm text-ink-500">
            เลือกวิธียืนยันตัวตนที่จะใช้ — ป้องกันบัญชีแม้รหัส Google หลุด
          </p>

          <div className="mt-4 grid gap-2 sm:grid-cols-3">
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

          <div className="mt-3 flex items-center gap-4">
            <button
              onClick={later}
              className="text-xs text-ink-400 hover:text-ink-600"
            >
              ไว้ทีหลัง
            </button>
            <button
              onClick={never}
              className="text-xs text-ink-400 hover:text-ink-600"
            >
              ไม่ต้องถามอีก
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
