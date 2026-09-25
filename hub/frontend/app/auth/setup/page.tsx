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
    icon: "",
    title: "Passkey",
    badge: "แนะนำ",
    desc: "ลายนิ้วมือ / Face / PIN — แข็งแรงสุด กัน phishing",
    tile: "bg-emerald-100 text-emerald-700",
    badgeCls: "bg-emerald-100 text-emerald-700",
    ring: "hover:border-emerald-400 hover:ring-emerald-100",
  },
  {
    key: "totp",
    icon: "",
    title: "Authenticator",
    badge: null,
    desc: "รหัส 6 หลักจากแอป — ใช้ได้ทุกอุปกรณ์",
    tile: "bg-slate-100 text-slate-700",
    badgeCls: "",
    ring: "hover:border-slate-400 hover:ring-slate-100",
  },
  {
    key: "both",
    icon: "",
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
  const [email, setEmail] = useState("");

  useEffect(() => {
    (async () => {
      const me = await fetch("/api/me", { credentials: "include" })
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null);
      const isAdmin = me?.is_hub_admin === true || me?.user_type === "admin";
      setEmail(typeof me?.email === "string" ? me.email : "");
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
      <main className="min-h-screen grid place-items-center bg-gradient-to-br from-ink-900 via-ink-800 to-brand-900 px-4">
        <div className="flex items-center gap-3 text-ink-300">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-white/70 border-t-transparent" />
          <span className="text-sm">กำลังเตรียมบัญชี…</span>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#f1f5f8] px-4 py-6 sm:px-6 lg:grid lg:place-items-center lg:py-10">
      <section className="mx-auto grid w-full max-w-6xl overflow-hidden border border-slate-300 bg-white shadow-[0_24px_70px_rgba(15,23,42,0.14)] lg:min-h-[650px] lg:grid-cols-[32%_68%]">
        <aside className="relative flex flex-col justify-between overflow-hidden bg-[#0b1728] px-7 py-8 text-white sm:px-10 lg:px-11">
          <div className="pointer-events-none absolute -right-28 -top-24 h-80 w-80 rounded-full bg-teal-400/10 blur-3xl" />
          <div className="relative">
            <div className="font-mono text-[11px] uppercase tracking-[0.2em] text-teal-300">Central Auth Hub</div>
            <div className="mt-1 font-mono text-[10px] uppercase tracking-[0.18em] text-slate-400">Identity Control</div>
            <div className="mt-14 font-mono text-[11px] uppercase tracking-[0.18em] text-slate-400">Account Security</div>
            <h1 className="mt-3 text-3xl font-extrabold leading-tight sm:text-4xl">เพิ่มความปลอดภัย<br className="hidden lg:block" />ให้บัญชี</h1>
            <p className="mt-4 max-w-sm text-sm leading-6 text-slate-300">
              เลือกวิธียืนยันตัวตนอีกชั้น เพื่อปกป้องบัญชีของคุณ แม้รหัส Google หลุด
            </p>
            {email && <p className="mt-4 break-all font-mono text-xs text-teal-300">{email}</p>}

            <ol className="mt-10 space-y-5">
              {[
                { n: "01", title: "เลือกวิธียืนยัน", detail: "Passkey หรือ Authenticator", active: true },
                { n: "02", title: "ตั้งค่าอุปกรณ์", detail: "ทำตามขั้นตอนบนหน้าจอ", active: false },
                { n: "03", title: "เสร็จสิ้น", detail: "กลับไปใช้งานบัญชี", active: false },
              ].map((step) => (
                <li key={step.n} className={`flex items-center gap-4 ${step.active ? "text-white" : "text-slate-500"}`}>
                  <span className={`grid h-9 w-9 shrink-0 place-items-center border font-mono text-xs ${step.active ? "border-teal-400 bg-teal-400/10 text-teal-300" : "border-slate-700 text-slate-500"}`}>{step.n}</span>
                  <span><b className="block text-sm">{step.title}</b><small className="mt-0.5 block text-xs">{step.detail}</small></span>
                </li>
              ))}
            </ol>
          </div>
          <div className="relative mt-10 border-t border-slate-700 pt-4 text-xs leading-5 text-slate-400">
            Passkey · WebAuthn · TOTP (RFC 6238)<br />
            ใช้อุปกรณ์ของคุณยืนยันตัวตนโดยตรง
          </div>
        </aside>

        <div className="flex min-w-0 flex-col">
          <header className="flex items-center justify-between gap-4 border-b border-slate-200 px-6 py-5 sm:px-10">
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-slate-500">Passkey / TOTP setup</div>
              <h2 className="mt-1 text-xl font-bold text-slate-900 sm:text-2xl">เลือกวิธีตั้งค่าการยืนยันตัวตน</h2>
            </div>
            <span className="shrink-0 border border-teal-200 bg-teal-50 px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-teal-800">Setup · Active</span>
          </header>

          <div className="flex flex-1 flex-col justify-center px-6 py-7 sm:px-10 sm:py-9">
            <p className="mb-5 max-w-2xl text-sm leading-6 text-slate-500">ตั้งค่าครั้งเดียว แล้วใช้ยืนยันตัวตนเมื่อเข้าใช้งานครั้งต่อไป เลือกวิธีที่เหมาะกับคุณ</p>
            <div className="space-y-3">
              {OPTIONS.map((o) => (
                <button
                  key={o.key}
                  type="button"
                  onClick={() => go(o.key)}
                  className={`group flex w-full items-center gap-4 border border-slate-200 bg-slate-50 p-4 text-left transition hover:border-teal-400 hover:bg-teal-50/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 sm:p-5`}
                >
                  <span className={`grid h-11 w-11 shrink-0 place-items-center border border-slate-200 bg-white font-mono text-xs font-bold text-teal-700`}>
                    {o.key === "passkey" ? "PK" : o.key === "totp" ? "6D" : "2FA"}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-2">
                      <b className="text-sm text-slate-900">{o.title}</b>
                      {o.badge && <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${o.badgeCls}`}>{o.badge}</span>}
                    </span>
                    <small className="mt-1 block text-xs leading-5 text-slate-500">{o.desc}</small>
                  </span>
                  <span className="shrink-0 text-xs font-semibold text-slate-500 transition group-hover:text-teal-700">ตั้งค่า <span aria-hidden="true">›</span></span>
                </button>
              ))}
            </div>

            <div className="mt-7 flex flex-col gap-3 border-t border-slate-200 pt-5 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs text-slate-500">ข้ามได้ — ตั้งค่าภายหลังในหน้า “บัญชีของฉัน”</p>
              <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                <button type="button" onClick={later} disabled={!!busy} className="min-h-10 border border-slate-300 px-4 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50">
                  {busy === "later" ? "กำลังบันทึก…" : "ไว้ทีหลัง"}
                </button>
                <button type="button" onClick={never} disabled={!!busy} className="min-h-10 border border-slate-300 px-4 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50">
                  {busy === "never" ? "กำลังบันทึก…" : "ไม่ต้องถามอีก"}
                </button>
              </div>
            </div>
          </div>
          <footer className="flex items-center justify-between border-t border-slate-200 bg-slate-50 px-6 py-4 font-mono text-[10px] uppercase tracking-wider text-slate-500 sm:px-10">
            <span>Secure account setup</span><span>2FA</span>
          </footer>
        </div>
      </section>
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
