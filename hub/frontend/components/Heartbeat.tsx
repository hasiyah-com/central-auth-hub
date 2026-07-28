"use client";

import { useEffect } from "react";
import { clientFetch } from "@/lib/api";

/**
 * Presence heartbeat — ยิง POST /auth/heartbeat เป็นระยะระหว่างเปิด console อยู่
 * เพื่อให้ Hub รู้ว่า session นี้ยัง active จริง (bump last_seen_at) → โชว์ online
 * ถูกต้องในหน้า /activity. หยุด ping เมื่อแท็บถูกซ่อน (ประหยัด + สะท้อน presence จริง)
 *
 * ใช้ stepupMode "throw" — heartbeat ไม่ควรเด้ง step-up/redirect ถ้า token มีปัญหา
 * (เป็น background ping ไม่ใช่ user action) → โยน error แล้ว .catch เงียบ
 */
export function Heartbeat({ intervalMs = 60000 }: { intervalMs?: number }) {
  useEffect(() => {
    let stopped = false;

    const ping = () => {
      if (stopped || document.visibilityState !== "visible") return;
      clientFetch("/auth/heartbeat", {
        method: "POST",
        stepupMode: "throw",
      }).catch(() => {
        /* background ping — เงียบเสมอ */
      });
    };

    ping(); // ครั้งแรกทันทีตอนเข้า console
    const timer = setInterval(ping, intervalMs);
    // ping ทันทีเมื่อกลับมาโฟกัสแท็บ (กัน last_seen ค้างตอนสลับไปแท็บอื่นนาน)
    const onVisible = () => {
      if (document.visibilityState === "visible") ping();
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      stopped = true;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [intervalMs]);

  return null;
}
