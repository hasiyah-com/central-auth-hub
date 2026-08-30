"use client";

/**
 * แถบท้าย console — บอกสถานะ Hub จริง ไม่ใช่ข้อความตายตัว
 *
 * เช็คจาก GET /health ของ Hub (endpoint สาธารณะ ไม่ต้อง auth) ผ่าน proxy เดิม
 * ทุก 60 วินาที → ถ้าเรียกไม่ได้จะแสดง "ติดต่อ Hub ไม่ได้" แทนการโชว์ว่าปกติ
 * (ห้ามโชว์ operational แบบไม่ได้ตรวจ — จะกลายเป็นข้อมูลลวง)
 *
 * ธีม: footer เป็น sibling ของ <main> ไม่ได้อยู่ข้างใน จึงไม่ได้รับพื้นดาร์กของเพจ
 * ต้องทาพื้นเองด้วยโทนเดียวกับพื้นเพจ (#0b1530) ไม่งั้นจะเป็นแถบสว่างใต้จอดาร์ก
 */

import { useEffect, useState } from "react";

type State = "checking" | "ok" | "down";

export function ConsoleFooter() {
  const [state, setState] = useState<State>("checking");

  useEffect(() => {
    let stopped = false;

    const check = () => {
      if (stopped) return;
      fetch("/api/proxy/health", { credentials: "include", cache: "no-store" })
        .then((r) => !stopped && setState(r.ok ? "ok" : "down"))
        .catch(() => !stopped && setState("down"));
    };

    check();
    const t = setInterval(check, 60_000);
    return () => {
      stopped = true;
      clearInterval(t);
    };
  }, []);

  const meta: Record<State, { dot: string; text: string; cls: string }> = {
    checking: { dot: "bg-ink-600", text: "กำลังตรวจสอบสถานะ", cls: "text-ink-500" },
    ok: { dot: "bg-emerald-400", text: "Hub ตอบสนองปกติ", cls: "text-emerald-400" },
    down: { dot: "bg-rose-400", text: "ติดต่อ Hub ไม่ได้", cls: "text-rose-400" },
  };
  const m = meta[state];

  return (
    <footer className="mt-auto border-t border-white/[.08] bg-[#0b1530] px-4 py-4 sm:px-6 lg:px-8">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 font-mono text-[10px] uppercase tracking-[.12em] text-ink-500">
        <span className="font-semibold text-ink-300">Central Auth Hub</span>
        <span>OAuth 2.0 · OIDC · PKCE</span>
        <span>RBAC · 4-Layer RBA</span>
        <span className={`ml-auto inline-flex items-center gap-2 normal-case tracking-normal ${m.cls}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${m.dot}`} />
          {m.text}
        </span>
      </div>
    </footer>
  );
}
