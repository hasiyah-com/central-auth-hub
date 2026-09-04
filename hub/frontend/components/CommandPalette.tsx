"use client";

/**
 * Command palette (⌘K / Ctrl+K) — ค้นเมนู + ค้นข้อมูลจริง
 *
 * 2 แหล่ง:
 *  1. เมนู  — จาก ADMIN_NAV / DEV_NAV ชุดเดียวกับ Sidebar (กรองฝั่ง client, ทันที)
 *  2. ข้อมูล — GET /admin/search (ผู้ใช้ / ระบบย่อย / IP) เรียกเมื่อพิมพ์ >= 2 ตัว
 *              debounce 250ms + ยกเลิกคำขอเก่าด้วย AbortController กันผลลัพธ์สลับลำดับ
 *
 * ผลลัพธ์ข้อมูลแสดงเฉพาะ admin (endpoint กัน RBAC อยู่แล้ว — ฝั่ง UI ไม่เรียกซ้ำถ้าไม่ใช่ admin)
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import clsx from "clsx";
import { ADMIN_NAV, DEV_NAV, type NavItem } from "@/components/Sidebar";

type Me = {
  user_type: string | null;
  is_hub_admin: boolean;
};

type SearchUser = {
  id: string;
  email: string;
  full_name: string | null;
  user_type: string | null;
  identifier: string | null;
  status: string | null;
};

type SearchSub = {
  id: string;
  name: string;
  client_id: string;
  status: string | null;
};

type SearchIp = { ip: string; sessions: number; last_seen: string | null };

type SearchResp = {
  query: string;
  users: SearchUser[];
  subsystems: SearchSub[];
  ips: SearchIp[];
};

type Row =
  | { kind: "nav"; key: string; href: string; label: string; hint: string }
  | { kind: "user"; key: string; href: string; label: string; hint: string }
  | { kind: "subsystem"; key: string; href: string; label: string; hint: string }
  | { kind: "ip"; key: string; href: string; label: string; hint: string };

const GROUP_LABEL: Record<Row["kind"], string> = {
  nav: "เมนู",
  user: "ผู้ใช้งาน",
  subsystem: "ระบบย่อย",
  ip: "IP address",
};

const GROUP_TAG: Record<Row["kind"], string> = {
  nav: "NAV",
  user: "USER",
  subsystem: "SUB",
  ip: "IP",
};

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [cursor, setCursor] = useState(0);
  const [me, setMe] = useState<Me | null>(null);
  const [remote, setRemote] = useState<SearchResp | null>(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch("/api/me", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  // เปิดด้วย ⌘K / Ctrl+K จากทุกที่ในหน้า
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) {
      setQ("");
      setCursor(0);
      setRemote(null);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const isAdmin = me?.is_hub_admin === true || me?.user_type === "admin";
  const isDeveloper =
    !!me && ["teacher", "staff", "admin"].includes(me.user_type || "");

  // ── ค้นข้อมูลจริง (debounce + ยกเลิกคำขอเก่า) ──
  useEffect(() => {
    const term = q.trim();
    if (!open || !isAdmin || term.length < 2) {
      setRemote(null);
      setLoading(false);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    const t = setTimeout(() => {
      fetch(`/api/proxy/admin/search?q=${encodeURIComponent(term)}&limit=5`, {
        credentials: "include",
        signal: ctrl.signal,
      })
        .then((r) => (r.ok ? r.json() : null))
        .then((d: SearchResp | null) => {
          setRemote(d);
          setLoading(false);
        })
        .catch((e) => {
          if ((e as Error).name !== "AbortError") setLoading(false);
        });
    }, 250);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [q, open, isAdmin]);

  const navItems: NavItem[] = useMemo(() => {
    const list: NavItem[] = [];
    if (isAdmin) list.push(...ADMIN_NAV);
    if (isDeveloper) list.push(...DEV_NAV);
    return list;
  }, [isAdmin, isDeveloper]);

  const rows: Row[] = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const navRows: Row[] = navItems
      .filter(
        (i) =>
          !needle ||
          i.label.toLowerCase().includes(needle) ||
          i.href.toLowerCase().includes(needle) ||
          (i.keywords || "").toLowerCase().includes(needle)
      )
      .map((i) => ({
        kind: "nav" as const,
        key: `nav:${i.href}`,
        href: i.href,
        label: i.label,
        hint: i.href,
      }));

    const out: Row[] = [...navRows];
    if (remote) {
      for (const u of remote.users) {
        out.push({
          kind: "user",
          key: `user:${u.id}`,
          href: `/users/${u.id}`,
          label: u.full_name || u.email,
          hint: [u.email, u.identifier, u.user_type].filter(Boolean).join(" · "),
        });
      }
      for (const s of remote.subsystems) {
        out.push({
          kind: "subsystem",
          key: `sub:${s.id}`,
          href: `/subsystems/${s.id}`,
          label: s.name,
          hint: [s.client_id, s.status].filter(Boolean).join(" · "),
        });
      }
      for (const ip of remote.ips) {
        out.push({
          kind: "ip",
          key: `ip:${ip.ip}`,
          href: `/activity?q=${encodeURIComponent(ip.ip)}`,
          label: ip.ip,
          hint: `${ip.sessions} session`,
        });
      }
    }
    return out;
  }, [navItems, q, remote]);

  useEffect(() => setCursor(0), [rows.length]);

  const go = useCallback(
    (href: string) => {
      setOpen(false);
      router.push(href);
    },
    [router]
  );

  // เลื่อนแถวที่เลือกให้อยู่ในสายตา
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-idx="${cursor}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  if (!open) return null;

  let lastKind: Row["kind"] | null = null;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center bg-ink-900/50 p-4 pt-[12vh] backdrop-blur-sm"
      onClick={() => setOpen(false)}
      role="dialog"
      aria-modal="true"
      aria-label="ค้นหา"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-xl overflow-hidden rounded-2xl border border-ink-200 bg-white shadow-2xl"
      >
        <div className="flex items-center gap-3 border-b border-ink-200 px-4 py-3">
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
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setCursor((c) => Math.min(c + 1, rows.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setCursor((c) => Math.max(c - 1, 0));
              } else if (e.key === "Enter" && rows[cursor]) {
                e.preventDefault();
                go(rows[cursor].href);
              }
            }}
            placeholder={
              isAdmin ? "ค้นหาเมนู, ผู้ใช้, client ID, IP…" : "ค้นหาเมนู…"
            }
            className="w-full bg-transparent text-sm text-ink-900 outline-none placeholder:text-ink-400"
          />
          {loading && (
            <span className="font-mono text-[9px] uppercase tracking-wider text-ink-400">
              กำลังค้น…
            </span>
          )}
          <kbd className="rounded border border-ink-200 px-1.5 py-0.5 font-mono text-[9px] text-ink-400">
            ESC
          </kbd>
        </div>

        <div ref={listRef} className="max-h-[54vh] overflow-y-auto py-1">
          {rows.length === 0 ? (
            <div className="px-4 py-10 text-center text-sm text-ink-400">
              {q.trim().length < 2
                ? "พิมพ์อย่างน้อย 2 ตัวอักษรเพื่อค้นข้อมูล"
                : loading
                  ? "กำลังค้น…"
                  : `ไม่พบผลลัพธ์สำหรับ “${q.trim()}”`}
            </div>
          ) : (
            rows.map((r, i) => {
              const header = r.kind !== lastKind ? GROUP_LABEL[r.kind] : null;
              lastKind = r.kind;
              return (
                <div key={r.key}>
                  {header && (
                    <div className="px-4 pb-1 pt-3 font-mono text-[9px] uppercase tracking-[.18em] text-ink-400">
                      {header}
                    </div>
                  )}
                  <button
                    data-idx={i}
                    onMouseEnter={() => setCursor(i)}
                    onClick={() => go(r.href)}
                    className={clsx(
                      "flex w-full items-center gap-3 border-l-2 px-4 py-2.5 text-left transition-colors",
                      i === cursor
                        ? "border-brand-500 bg-brand-50"
                        : "border-transparent hover:bg-ink-50"
                    )}
                  >
                    <span
                      className={clsx(
                        "w-10 shrink-0 rounded border px-1 py-0.5 text-center font-mono text-[8px] font-bold uppercase tracking-wider",
                        i === cursor
                          ? "border-brand-500/40 bg-brand-500/10 text-brand-700"
                          : "border-ink-200 text-ink-400"
                      )}
                    >
                      {GROUP_TAG[r.kind]}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-ink-900">
                        {r.label}
                      </span>
                      {r.hint && (
                        <span className="block truncate font-mono text-[10px] text-ink-400">
                          {r.hint}
                        </span>
                      )}
                    </span>
                  </button>
                </div>
              );
            })
          )}
        </div>

        <div className="flex items-center gap-3 border-t border-ink-200 px-4 py-2 font-mono text-[9px] uppercase tracking-wider text-ink-400">
          <span>↑↓ เลือก</span>
          <span>↵ เปิด</span>
          <span className="ml-auto">{rows.length} รายการ</span>
        </div>
      </div>
    </div>
  );
}
