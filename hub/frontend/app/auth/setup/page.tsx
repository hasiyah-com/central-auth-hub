"use client";

// useSearchParams() ต้อง render ตอน request time — กัน prerender error ตอน next build
export const dynamic = "force-dynamic";

/**
 * หน้า interstitial "เพิ่มความปลอดภัยให้บัญชี" — แสดง **ครั้งเดียวหลัง login**
 * สำหรับ user ที่ยังไม่มี factor (should_prompt_setup) ก่อนเข้าหน้าหลัก.
 *
 * ธีมเดียวกับหน้า login: dark indigo hero + การ์ดขาวยกลอย. เลือกวิธี → ไปหน้า account
 * ตั้งค่าจริง; "ไว้ทีหลัง" = snooze 7 วัน; "ไม่ต้องถามอีก" = ปิดถาวร. ทั้ง 3 ทางออกไป
 * `next` (หน้าหลักตาม role).
 */

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  fetchSecurityStatus,
  dismissSecurityOnboarding,
  snoozeSecurityOnboarding,
} from "@/lib/passkey";

type Factor = "passkey" | "totp" | "both";

const OPTIONS: {
  key: Factor;
  icon: string;
  title: string;
  badge: string | null;
  desc: string;
  tile: string;
  badgeCls: string;
  ring: string;
}[] = [
  {
    key: "passkey",
    icon: "🔑",
    title: "Passkey",
    badge: "แนะนำ",
    desc: "ลายนิ้วมือ / Face / PIN — แข็งแรงสุด กัน phishing",
    tile: "bg-emerald-100 text-emerald-700",
    badgeCls: "bg-emerald-100 text-emerald-700",
    ring: "hover:border-emerald-400 hover:ring-emerald-100",
  },
  {
    key: "totp",
    icon: "📱",
    title: "Authenticator",
    badge: null,
    desc: "รหัส 6 หลักจากแอป — ใช้ได้ทุกอุปกรณ์",
    tile: "bg-slate-100 text-slate-700",
    badgeCls: "",
    ring: "hover:border-slate-400 hover:ring-slate-100",
  },
  {
    key: "both",
    icon: "✨",
    title: "ทั้งสอง",
    badge: "ปลอดภัยสุด",
    desc: "Passkey หลัก + Authenticator สำรองไว้กู้บัญชี",
    tile: "bg-brand-100 text-brand-700",
    badgeCls: "bg-brand-100 text-brand-700",
    ring: "hover:border-brand-400 hover:ring-brand-100",
  },
];

function SetupInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [ready, setReady] = useState(false);
  const [accountHref, setAccountHref] = useState("/account");
  const [dest, setDest] = useState("/dashboard");
  const [busy, setBusy] = useState<"" | "later" | "never">("");

  useEffect(() => {
    (async () => {
      const me = await fetch("/api/me", { credentials: "include" })
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null);
      const isAdmin = me?.is_hub_admin === true || me?.user_type === "admin";
      const home = isAdmin ? "/dashboard" : "/developer/subsystems";
      const acct = isAdmin ? "/account" : "/developer/account";
      const next = params.get("next") || home;
      setAccountHref(acct);
      setDest(next);

      // มี factor แล้ว / ปิดถาวร / อยู่ในช่วง snooze → ข้ามไปหน้าหลักเลย
      const status = await fetchSecurityStatus().catch(() => null);
      if (!status || !status.should_prompt_setup) {
        window.location.href = next;
        return;
      }
      setReady(true);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const go = (setup: Factor) => router.push(`${accountHref}?setup=${setup}`);

  const later = async () => {
    setBusy("later");
    try {
      await snoozeSecurityOnboarding(); // พัก 7 วัน (ผูกกับบัญชี)
    } catch {
      /* fail-safe */
    }
    window.location.href = dest;
  };

  const never = async () => {
    setBusy("never");
    try {
      await dismissSecurityOnboarding();
    } catch {
      /* fail-safe */
    }
    window.location.href = dest;
  };

  if (!ready) {
    return (
      <main className="cx-auth">
        <div className="flex items-center gap-3 text-ink-300">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-white/70 border-t-transparent" />
          <span className="text-sm">กำลังเตรียมบัญชี…</span>
        </div>
      </main>
    );
  }

  return (
    <main className="cx-auth cx-setup">
      <a className="cx-auth-brand" href="/auth/login"><b>HUB</b><span className="mono">IDENTITY CONTROL</span></a>
      <div className="cx-auth-card cx-setup-card reveal">
        {/* accent bar */}
        <div className="h-1.5 bg-gradient-to-r from-emerald-400 via-brand-500 to-brand-700" />

        <div className="px-7 pb-7 pt-8 sm:px-10 sm:pb-9">
          {/* header */}
          <div
            className="reveal flex items-center gap-3"
            style={{ animationDelay: "60ms" }}
          >
            <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand-600 to-brand-900 text-xl text-white shadow-md">
              🛡️
            </div>
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-brand-600">
                Central Auth Hub
              </div>
              <h1 className="text-xl font-extrabold text-ink-900 sm:text-2xl">
                เพิ่มความปลอดภัยให้บัญชี
              </h1>
            </div>
          </div>

          <p
            className="reveal mt-3 max-w-xl text-sm leading-relaxed text-ink-500"
            style={{ animationDelay: "110ms" }}
          >
            เลือกวิธียืนยันตัวตนอีกชั้น เพื่อให้บัญชีปลอดภัยแม้รหัส Google หลุด —
            ตั้งครั้งเดียว ใช้ได้ตลอด
          </p>

          {/* options */}
          <div className="mt-6 grid gap-3 sm:grid-cols-3">
            {OPTIONS.map((o, i) => (
              <button
                key={o.key}
                onClick={() => go(o.key)}
                style={{ animationDelay: `${180 + i * 80}ms` }}
                className={`reveal group relative flex flex-col gap-3 rounded-2xl border border-ink-200 bg-white p-4 text-left transition-all duration-200 hover:-translate-y-1 hover:shadow-lg hover:ring-4 ${o.ring} focus:outline-none focus-visible:ring-4 focus-visible:ring-brand-200`}
              >
                <div className="flex items-start justify-between">
                  <span
                    className={`grid h-11 w-11 place-items-center rounded-xl text-xl ${o.tile}`}
                  >
                    {o.icon}
                  </span>
                  {o.badge && (
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${o.badgeCls}`}
                    >
                      {o.badge}
                    </span>
                  )}
                </div>
                <div>
                  <div className="text-sm font-bold text-ink-900">{o.title}</div>
                  <div className="mt-1 text-xs leading-relaxed text-ink-400">
                    {o.desc}
                  </div>
                </div>
                <div className="mt-auto flex items-center gap-1 pt-1 text-xs font-semibold text-ink-400 transition-colors group-hover:text-brand-600">
                  ตั้งค่า
                  <span className="transition-transform duration-200 group-hover:translate-x-0.5">
                    →
                  </span>
                </div>
              </button>
            ))}
          </div>

          {/* footer actions */}
          <div
            className="reveal mt-7 flex flex-col gap-3 border-t border-ink-100 pt-5 sm:flex-row sm:items-center sm:justify-between"
            style={{ animationDelay: "440ms" }}
          >
            <p className="text-xs text-ink-400">
              ข้ามไปก่อนได้ — ตั้งภายหลังในหน้า “บัญชีของฉัน”
            </p>
            <div className="flex items-center gap-2">
              <button
                onClick={later}
                disabled={!!busy}
                className="rounded-lg px-3 py-2 text-sm font-medium text-ink-500 transition hover:bg-ink-50 hover:text-ink-800 disabled:opacity-50"
              >
                {busy === "later" ? "กำลังบันทึก…" : "ไว้ทีหลัง"}
              </button>
              <button
                onClick={never}
                disabled={!!busy}
                className="rounded-lg px-3 py-2 text-sm text-ink-400 transition hover:text-ink-600 disabled:opacity-50"
              >
                {busy === "never" ? "กำลังบันทึก…" : "ไม่ต้องถามอีก"}
              </button>
            </div>
          </div>
        </div>

        {/* security strip — tie to login footer */}
        <div className="flex items-center justify-between border-t border-ink-100 bg-ink-50 px-7 py-4 text-xs text-ink-500 sm:px-10">
          <span>Passkey · WebAuthn · TOTP (RFC 6238)</span>
          <span className="font-mono text-ink-400">2FA</span>
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
