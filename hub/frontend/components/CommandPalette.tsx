"use client";

/**
 * Command palette (⌘K / Ctrl+K) — quick-nav ไปหน้าใน console
 *
 * ใช้รายการเมนูชุดเดียวกับ Sidebar (ADMIN_NAV / DEV_NAV) จึงไม่ต้อง sync สองที่
 * และกรองตามสิทธิ์จริงของผู้ใช้เหมือน Sidebar (admin / developer)
 *
 * ธีม: console เป็นพื้นดาร์ก จึงใช้สำนวนสีชุดเดียวกับ Sidebar —
 * พาเนลใช้ --canvas-panel (#111726) ให้ดู "ลอย" เหนือพื้นหน้า, เส้นขอบ white/10,
 * ตัวอักษร ink-100/400/500 และไฮไลต์ด้วย brand-500
 *
 * ตั้งใจให้ทำงานจริง ไม่ใช่ช่องค้นหาหลอก — ถ้าอนาคตมี global search ฝั่ง backend
 * ค่อยต่อยอดจากที่นี่
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import clsx from "clsx";
import { ADMIN_NAV, DEV_NAV, type NavItem } from "@/components/Sidebar";

type Me = {
  user_type: string | null;
  is_hub_admin: boolean;
};

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [cursor, setCursor] = useState(0);
  const [me, setMe] = useState<Me | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

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
      // รอ modal mount ก่อนโฟกัส
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const isAdmin = me?.is_hub_admin === true || me?.user_type === "admin";
  const isDeveloper =
    !!me && ["teacher", "staff", "admin"].includes(me.user_type || "");

  const items: NavItem[] = useMemo(() => {
    const list: NavItem[] = [];
    if (isAdmin) list.push(...ADMIN_NAV);
    if (isDeveloper) list.push(...DEV_NAV);
    return list;
  }, [isAdmin, isDeveloper]);

  const results = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return items;
    return items.filter(
      (i) =>
        i.label.toLowerCase().includes(needle) ||
        i.href.toLowerCase().includes(needle) ||
        i.glyph.toLowerCase().includes(needle)
    );
  }, [items, q]);

  const go = useCallback(
    (href: string) => {
      setOpen(false);
      router.push(href);
    },
    [router]
  );

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center bg-ink-900/75 p-4 pt-[12vh] backdrop-blur-sm"
      onClick={() => setOpen(false)}
      role="dialog"
      aria-modal="true"
      aria-label="ค้นหาเมนู"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-lg overflow-hidden rounded-2xl border border-white/10 bg-[#111726] shadow-2xl"
      >
        <div className="flex items-center gap-3 border-b border-white/[.08] px-4 py-3">
          <span className="font-mono text-[10px] uppercase tracking-[.16em] text-ink-500">
            go to
          </span>
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setCursor(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setCursor((c) => Math.min(c + 1, results.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setCursor((c) => Math.max(c - 1, 0));
              } else if (e.key === "Enter" && results[cursor]) {
                e.preventDefault();
                go(results[cursor].href);
              }
            }}
            placeholder="พิมพ์ชื่อหน้า เช่น ผู้ใช้ / audit / ml"
            className="w-full bg-transparent text-sm text-ink-100 outline-none placeholder:text-ink-500"
          />
          <kbd className="rounded border border-white/15 px-1.5 py-0.5 font-mono text-[9px] text-ink-400">
            ESC
          </kbd>
        </div>

        <div className="max-h-[52vh] overflow-y-auto py-1">
          {results.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-ink-500">
              ไม่พบเมนูที่ตรงกับ &ldquo;{q}&rdquo;
            </div>
          ) : (
            results.map((item, i) => (
              <button
                key={item.href}
                onMouseEnter={() => setCursor(i)}
                onClick={() => go(item.href)}
                className={clsx(
                  "flex w-full items-center gap-3 border-l-2 px-4 py-2.5 text-left transition-colors",
                  i === cursor
                    ? "border-brand-500 bg-brand-500/10"
                    : "border-transparent hover:bg-white/[.04]"
                )}
              >
                <span
                  className={clsx(
                    "grid h-6 w-6 shrink-0 place-items-center rounded border font-mono text-[9px] font-semibold",
                    i === cursor
                      ? "border-brand-500/40 bg-brand-500/10 text-brand-500"
                      : "border-white/10 text-ink-500"
                  )}
                >
                  {item.glyph}
                </span>
                <span className="flex-1 truncate text-sm font-medium text-ink-100">
                  {item.label}
                </span>
                <span className="truncate font-mono text-[10px] text-ink-500">
                  {item.href}
                </span>
              </button>
            ))
          )}
        </div>

        <div className="flex items-center gap-3 border-t border-white/[.08] px-4 py-2 font-mono text-[9px] uppercase tracking-wider text-ink-500">
          <span>↑↓ เลือก</span>
          <span>↵ ไป</span>
          <span className="ml-auto">{results.length} รายการ</span>
        </div>
      </div>
    </div>
  );
}
