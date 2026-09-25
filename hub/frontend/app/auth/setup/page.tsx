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
  registerPasskey,
} from "@/lib/passkey";
import { TotpCard } from "@/components/account/TotpCard";
import { BackupCodesModal } from "@/components/account/BackupCodesModal";

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
  const [required, setRequired] = useState(false);
  const [gateError, setGateError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const me = await fetch("/api/me", { credentials: "include" })
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null);
      setEmail(typeof me?.email === "string" ? me.email : "");

      const status = await fetchSecurityStatus().catch(() => null);
      if (!status) {
        setGateError("ตรวจสอบสถานะความปลอดภัยไม่ได้ กรุณาลองใหม่ก่อนเข้าใช้งาน");
        setReady(true);
        return;
      }

      const isAdmin = status.is_admin || me?.is_hub_admin === true || me?.user_type === "admin";
      const home = isAdmin ? "/dashboard" : "/developer/subsystems";
      const acct = isAdmin ? "/account" : "/developer/account";
      const requestedNext = params.get("next") || home;
      const next = requestedNext.startsWith("/") && !requestedNext.startsWith("//")
        ? requestedNext
        : home;
      setAccountHref(acct);
      setDest(next);

      // admin ที่ยังไม่มี factor ต้องตั้งค่าจริงก่อนเข้าหน้าหลัก แม้เคยกด snooze/dismiss
      const mustSetup = status.is_admin && !status.has_second_factor;
      setRequired(mustSetup);
      if (!mustSetup && !status.should_prompt_setup) {
        window.location.href = next;
        return;
      }
      setReady(true);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const go = (setup: Factor) => {
    if (required) {
      const query = new URLSearchParams({ enroll: setup, required: "1", next: dest });
      router.push(`/auth/setup?${query.toString()}`);
      return;
    }
    const query = new URLSearchParams({ setup });
    router.push(`${accountHref}?${query.toString()}`);
  };

  const later = async () => {
    if (required) return;
    setBusy("later");
    try {
      await snoozeSecurityOnboarding(); // พัก 7 วัน (ผูกกับบัญชี)
    } catch {
      /* fail-safe */
    }
    window.location.href = dest;
  };

  const never = async () => {
    if (required) return;
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

  const enrollFactor = params.get("enroll");
  const nextParam = params.get("next") || dest;
  const safeNext = nextParam.startsWith("/") && !nextParam.startsWith("//") ? nextParam : "/dashboard";
  if (required && (enrollFactor === "passkey" || enrollFactor === "totp" || enrollFactor === "both")) {
    return <RequiredEnrollment factor={enrollFactor} next={safeNext} email={email} />;
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
            {required ? (
              <p className="mb-5 max-w-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900">
                บัญชีผู้ดูแลระบบต้องลงทะเบียนวิธีที่เลือกให้สำเร็จก่อน จึงจะเข้าใช้งานหน้าหลักได้
              </p>
            ) : (
              <p className="mb-5 max-w-2xl text-sm leading-6 text-slate-500">ตั้งค่าครั้งเดียว แล้วใช้ยืนยันตัวตนเมื่อเข้าใช้งานครั้งต่อไป เลือกวิธีที่เหมาะกับคุณ</p>
            )}
            {gateError && (
              <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
                <span>{gateError}</span>
                <button type="button" onClick={() => window.location.reload()} className="font-semibold underline">ลองตรวจสอบอีกครั้ง</button>
              </div>
            )}
            <div className="space-y-3">
              {OPTIONS.map((o) => (
                <button
                  key={o.key}
                  type="button"
                  onClick={() => go(o.key)}
                  disabled={!!gateError}
                  className={`group flex w-full items-center gap-4 border border-slate-200 bg-slate-50 p-4 text-left transition hover:border-teal-400 hover:bg-teal-50/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 disabled:cursor-not-allowed disabled:opacity-50 sm:p-5`}
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
              {required ? (
                <p className="text-xs font-medium text-slate-600">ต้องลงทะเบียนวิธีที่เลือกให้เสร็จก่อน จึงจะไปหน้าหลักได้</p>
              ) : (
                <>
                  <p className="text-xs text-slate-500">ข้ามได้ — ตั้งค่าภายหลังในหน้า “บัญชีของฉัน”</p>
                  <div className="flex flex-wrap items-center gap-2 sm:justify-end">
                    <button type="button" onClick={later} disabled={!!busy} className="min-h-10 border border-slate-300 px-4 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50">
                      {busy === "later" ? "กำลังบันทึก…" : "ไว้ทีหลัง"}
                    </button>
                    <button type="button" onClick={never} disabled={!!busy} className="min-h-10 border border-slate-300 px-4 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50">
                      {busy === "never" ? "กำลังบันทึก…" : "ไม่ต้องถามอีก"}
                    </button>
                  </div>
                </>
              )}
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


function RequiredEnrollment({ factor, next, email }: { factor: Factor; next: string; email: string }) {
  const [deviceName, setDeviceName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [status, setStatus] = useState<{ has_passkey: boolean; has_totp: boolean } | null>(null);

  useEffect(() => {
    let cancelled = false;
    let redirected = false;
    const check = async () => {
      try {
        const current = await fetchSecurityStatus();
        if (cancelled || redirected) return;
        setStatus(current);
        const complete = factor === "passkey" ? current.has_passkey
          : factor === "totp" ? current.has_totp
          : current.has_passkey && current.has_totp;
        if (complete && !backupCodes) {
          redirected = true;
          window.location.replace(next);
        }
      } catch {
        if (!cancelled) setError("ตรวจสอบสถานะการลงทะเบียนไม่ได้ กรุณาลองอีกครั้ง");
      }
    };
    void check();
    const timer = window.setInterval(() => void check(), 1500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [factor, next, backupCodes]);

  const submitPasskey = async () => {
    if (!deviceName.trim()) { setError("กรุณาตั้งชื่ออุปกรณ์"); return; }
    setBusy(true);
    setError(null);
    try {
      const result = await registerPasskey(deviceName.trim());
      setDeviceName("");
      if (result.backup_codes && result.backup_codes_must_acknowledge) setBackupCodes(result.backup_codes);
      else setStatus(await fetchSecurityStatus());
    } catch (e) {
      setError(e instanceof Error ? e.message : "ลงทะเบียน Passkey ไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  };

  const passkeyReady = status?.has_passkey === true;
  const showTotp = factor === "totp" || (factor === "both" && passkeyReady && !status?.has_totp);
  const title = factor === "passkey" ? "ลงทะเบียน Passkey" : factor === "totp" ? "ลงทะเบียน Authenticator" : "ลงทะเบียน Passkey และ Authenticator";

  return (
    <main className="min-h-screen bg-[#f1f5f8] px-4 py-8 sm:px-6">
      <section className="mx-auto w-full max-w-3xl overflow-hidden border border-slate-300 bg-white shadow-[0_24px_70px_rgba(15,23,42,0.14)]">
        <header className="bg-[#0b1728] px-6 py-7 text-white sm:px-10">
          <div className="font-mono text-[11px] uppercase tracking-[0.2em] text-teal-300">Central Auth Hub · Required security setup</div>
          <h1 className="mt-3 text-2xl font-bold sm:text-3xl">{title}</h1>
          <p className="mt-2 text-sm text-slate-300">ลงทะเบียนวิธีที่เลือกให้สำเร็จก่อน จึงจะเข้าใช้งานหน้าหลักของผู้ดูแลระบบได้</p>
          {email && <p className="mt-3 break-all font-mono text-xs text-teal-300">{email}</p>}
        </header>
        <div className="space-y-5 p-6 sm:p-10">
          {factor !== "totp" && !passkeyReady && (
            <section className="border border-slate-200 p-5">
              <h2 className="font-semibold text-slate-900">Passkey</h2>
              <p className="mt-1 text-sm text-slate-500">ใช้ลายนิ้วมือ, Face ID, PIN หรือ security key เพื่อยืนยันตัวตน</p>
              <label className="mt-4 block text-xs font-medium text-slate-600" htmlFor="required-device-name">ชื่ออุปกรณ์</label>
              <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                <input id="required-device-name" value={deviceName} onChange={(e) => setDeviceName(e.target.value)} placeholder="เช่น คอมพิวเตอร์สำนักงาน" disabled={busy} className="min-h-11 flex-1 border border-slate-300 px-3 text-sm" />
                <button type="button" onClick={submitPasskey} disabled={busy} className="min-h-11 bg-teal-600 px-5 text-sm font-semibold text-white disabled:opacity-50">{busy ? "กำลังลงทะเบียน…" : "ลงทะเบียน Passkey"}</button>
              </div>
            </section>
          )}
          {showTotp && (
            <section className="border border-slate-200 p-4 sm:p-5">
              {factor === "both" && <p className="mb-4 text-sm text-slate-600">Passkey ลงทะเบียนแล้ว ขั้นต่อไปให้ตั้งค่า Authenticator</p>}
              <TotpCard />
            </section>
          )}
          {factor === "passkey" && passkeyReady && !backupCodes && (
            <div className="border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">ลงทะเบียน Passkey สำเร็จ กำลังพาไปหน้าหลัก…</div>
          )}
          {factor === "totp" && status?.has_totp && (
            <div className="border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">ลงทะเบียน Authenticator สำเร็จ กำลังพาไปหน้าหลัก…</div>
          )}
          {factor === "both" && passkeyReady && status?.has_totp && (
            <div className="border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">ลงทะเบียนทั้งสองวิธีสำเร็จ กำลังพาไปหน้าหลัก…</div>
          )}
          {error && <div role="alert" className="border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div>}
        </div>
      </section>
      {backupCodes && <BackupCodesModal codes={backupCodes} onAcknowledged={() => setBackupCodes(null)} />}
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
