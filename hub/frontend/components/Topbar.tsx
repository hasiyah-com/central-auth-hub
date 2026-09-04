"use client";

/**
 * Topbar — Signal Room layout
 *
 * ซ้าย: breadcrumb · กลาง-ขวา: ช่องค้นหา (⌘K) · ขวา: กระดิ่งแจ้งเตือน + นาฬิกา + ผู้ใช้
 *
 * ช่องค้นหาเปิด CommandPalette ซึ่งค้นทั้งเมนูและข้อมูลจริงผ่าน /admin/search
 * (ผู้ใช้ / ระบบย่อย / IP) — placeholder ต่างกันตามสิทธิ์ เพราะ non-admin ค้นได้แค่เมนู
 *
 * กระดิ่งใช้จำนวนที่ยังไม่อ่านจริงจาก /admin/notifications/count
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { CommandPalette } from "@/components/CommandPalette";

type Me = {
  email: string;
  full_name: string | null;
  user_type: string | null;
  faculty: string | null;
  is_hub_admin: boolean;
};

type NotifCount = { total: number; unread?: number };

function avatarColor(value: string) {
  let hash = 0;
  for (let i = 0; i < value.length; i++) hash = value.charCodeAt(i) + ((hash << 5) - hash);
  return `hsl(${Math.abs(hash) % 360} 58% 42%)`;
}

function openPalette() {
  document.dispatchEvent(
    new KeyboardEvent("keydown", { key: "k", metaKey: true, ctrlKey: true, bubbles: true })
  );
}

export function Topbar({ title }: { title: string }) {
  const [me, setMe] = useState<Me | null>(null);
  const [notif, setNotif] = useState<NotifCount | null>(null);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    fetch("/api/me", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  useEffect(() => {
    if (!me?.is_hub_admin) return;
    const load = () =>
      fetch("/api/proxy/admin/notifications/count", { credentials: "include" })
        .then((r) => (r.ok ? r.json() : null))
        .then(setNotif)
        .catch(() => undefined);
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, [me]);

  async function logout() {
    await fetch("/api/set-token", { method: "DELETE", credentials: "include" });
    router.push("/auth/login");
  }

  const identity = me?.full_name || me?.email || "?";
  const initial = identity.charAt(0).toUpperCase();
  const color = useMemo(() => avatarColor(me?.email || identity), [me?.email, identity]);
  const unread = notif?.unread ?? 0;
  const isDeveloperArea = pathname.startsWith("/developer");

  return (
    <>
      <header className="sticky top-0 z-20 flex min-h-[64px] items-center gap-4 border-b border-ink-200 bg-white/95 px-4 pl-16 backdrop-blur-xl sm:px-6 sm:pl-16 lg:px-8">
        {/* breadcrumb */}
        <div className="min-w-0 shrink-0">
          <nav className="flex items-center gap-2 truncate">
            <Link
              href={isDeveloperArea ? "/developer/subsystems" : "/dashboard"}
              className="font-mono text-[10px] font-semibold uppercase tracking-[.18em] text-ink-400 hover:text-ink-600"
            >
              hub
            </Link>
            <span className="text-ink-300">/</span>
            <span className="truncate text-sm font-semibold text-ink-900">{title}</span>
          </nav>
        </div>

        {/* search → command palette */}
        <button
          onClick={openPalette}
          className="ml-auto hidden h-9 w-full max-w-md items-center gap-2.5 rounded-lg border border-ink-200 bg-ink-50/60 px-3 text-left transition hover:border-ink-300 hover:bg-white md:flex"
          aria-label="ค้นหาเมนู"
        >
          <svg
            viewBox="0 0 18 18"
            className="h-4 w-4 shrink-0 text-ink-400"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          >
            <circle cx="8" cy="8" r="5.2" />
            <path d="M11.9 11.9 15.5 15.5" />
          </svg>
          <span className="flex-1 truncate text-xs text-ink-400">
            {me?.is_hub_admin ? "ค้นหาผู้ใช้, client ID, IP…" : "ค้นหาเมนู…"}
          </span>
          <kbd className="rounded border border-ink-200 bg-white px-1.5 py-0.5 font-mono text-[9px] text-ink-400">
            ⌘K
          </kbd>
        </button>

        <div className="ml-auto flex items-center gap-1 md:ml-0">
          {/* notifications */}
          {me?.is_hub_admin && (
            <Link
              href="/notifications"
              className="relative grid h-9 w-9 place-items-center rounded-lg text-ink-500 transition hover:bg-ink-50 hover:text-ink-900"
              aria-label={unread > 0 ? `แจ้งเตือน ${unread} รายการ` : "แจ้งเตือน"}
            >
              <svg
                viewBox="0 0 18 18"
                className="h-[18px] w-[18px]"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M4.5 7.5a4.5 4.5 0 0 1 9 0c0 3.2 1 4.5 1 4.5H3.5s1-1.3 1-4.5z" />
                <path d="M7.4 14.5a1.8 1.8 0 0 0 3.2 0" />
              </svg>
              {unread > 0 && (
                <span className="absolute right-1 top-1 min-w-[15px] rounded-full bg-rose-500 px-1 text-center font-mono text-[8px] font-bold leading-[15px] text-white">
                  {unread > 99 ? "99+" : unread}
                </span>
              )}
            </Link>
          )}

          <Clock />

          {/* identity */}
          {me && (
            <div className="ml-1 flex items-center gap-2.5 border-l border-ink-200 pl-3">
              <div className="hidden text-right lg:block">
                <div className="max-w-44 truncate text-xs font-semibold text-ink-900">
                  {identity}
                </div>
                <div className="max-w-44 truncate font-mono text-[9px] text-ink-500">
                  {me.email}
                </div>
              </div>
              <div
                className="grid h-8 w-8 place-items-center rounded-lg text-xs font-bold text-white"
                style={{ backgroundColor: color }}
              >
                {initial}
              </div>
              <button
                onClick={logout}
                className="grid h-9 w-9 place-items-center rounded-lg text-ink-400 transition hover:bg-ink-50 hover:text-rose-600"
                aria-label="ออกจากระบบ"
                title="ออกจากระบบ"
              >
                <svg
                  viewBox="0 0 18 18"
                  className="h-[18px] w-[18px]"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M7 15.5H3.8a1.3 1.3 0 0 1-1.3-1.3V3.8A1.3 1.3 0 0 1 3.8 2.5H7" />
                  <path d="M11.5 12.5 15 9l-3.5-3.5M15 9H6.5" />
                </svg>
              </button>
            </div>
          )}
        </div>
      </header>
      <CommandPalette />
    </>
  );
}

/** นาฬิกาเวลาไทย (ICT) — ให้ admin เทียบ timestamp ในหน้าอื่นได้ทันที */
function Clock() {
  const [now, setNow] = useState<string | null>(null);
  useEffect(() => {
    const tick = () =>
      setNow(
        new Date().toLocaleTimeString("th-TH", {
          timeZone: "Asia/Bangkok",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        })
      );
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, []);
  if (!now) return null;
  return (
    <div className="hidden items-center gap-1.5 rounded-lg px-2 py-1.5 md:flex">
      <svg
        viewBox="0 0 18 18"
        className="h-[15px] w-[15px] text-ink-400"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      >
        <circle cx="9" cy="9" r="6.8" />
        <path d="M9 5v4.2l2.8 1.6" />
      </svg>
      <span className="font-mono text-[11px] tabular-nums text-ink-600">{now}</span>
      <span className="font-mono text-[9px] text-ink-400">ICT</span>
    </div>
  );
}
