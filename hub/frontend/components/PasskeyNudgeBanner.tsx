"use client";

/**
 * PasskeyNudgeBanner — soft nudge เตือนตั้งค่า Passkey (Phase 7, soft enforcement).
 *
 * เรียก GET /auth/passkey/adoption หลัง mount — เปิดกับทุก role (admin/developer,
 * ไม่จำกัดแค่ admin) เพราะทั้งคู่ login ผ่าน Hub-direct OAuth เส้นทางเดียวกัน.
 * แสดงเมื่อ nudge=true (account เกิน PASSKEY_REQUIRED_AFTER_DAYS วัน + ยังไม่มี
 * passkey) — ไม่ block การใช้งาน แค่เตือน + ลิงก์ไปตั้งค่า.
 *
 * Dismiss เก็บใน sessionStorage — ปิดแล้วไม่โผล่ซ้ำจนกว่าจะ login ใหม่
 * (ต่างจาก localStorage ที่จะปิดถาวรแม้ยังไม่มี passkey จริง).
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { clientFetch } from "@/lib/api";

type AdoptionStatus = {
  has_passkey: boolean;
  nudge: boolean;
  days_since_signup: number;
  required_after_days: number;
};

const DISMISS_KEY = "passkey_nudge_dismissed";

export function PasskeyNudgeBanner({ accountHref }: { accountHref: string }) {
  const [status, setStatus] = useState<AdoptionStatus | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined" && sessionStorage.getItem(DISMISS_KEY)) {
      setDismissed(true);
      return;
    }
    clientFetch<AdoptionStatus>("/auth/passkey/adoption")
      .then(setStatus)
      .catch(() => setStatus(null)); // fail-safe — เงียบถ้าเรียกไม่สำเร็จ ไม่รบกวนผู้ใช้
  }, []);

  if (dismissed || !status?.nudge) return null;

  const handleDismiss = () => {
    sessionStorage.setItem(DISMISS_KEY, "1");
    setDismissed(true);
  };

  return (
    <div className="mx-8 mt-4 flex items-center justify-between gap-4 rounded-xl border border-amber-200 bg-amber-50 px-5 py-3">
      <div className="flex items-center gap-3 min-w-0">
        <span className="text-xl shrink-0">🔑</span>
        <p className="text-sm text-amber-900 min-w-0">
          <strong>บัญชีของคุณยังไม่มี Passkey</strong> — ใช้งานมาแล้ว{" "}
          {status.days_since_signup} วัน เพิ่ม Passkey เพื่อ login แบบไม่ใช้
          รหัสผ่านและปลอดภัยยิ่งขึ้น
        </p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <Link
          href={accountHref}
          className="px-3 py-1.5 rounded-lg bg-amber-600 text-white text-sm font-semibold hover:bg-amber-700 whitespace-nowrap"
        >
          ตั้งค่าเลย
        </Link>
        <button
          onClick={handleDismiss}
          aria-label="ปิดการแจ้งเตือน"
          className="text-amber-500 hover:text-amber-700 text-lg leading-none px-1"
        >
          ×
        </button>
      </div>
    </div>
  );
}
