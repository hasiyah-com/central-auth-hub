"use client";

import { useEffect } from "react";

export const IDLE_TIMEOUT_MS = 30 * 60 * 1000;
const ACTIVITY_KEY = "hub:last-user-activity";
const LOGOUT_KEY = "hub:idle-logout";
const ACTIVITY_WRITE_THROTTLE_MS = 5_000;
const CHECK_INTERVAL_MS = 10_000;

async function revokeAndRedirect() {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 8_000);
  try {
    await fetch("/api/set-token", {
      method: "DELETE",
      credentials: "include",
      signal: controller.signal,
    });
  } finally {
    window.clearTimeout(timeout);
    // route ฝั่ง Next เคลียร์ cookies แม้ Hub backend ติดต่อไม่ได้
    window.location.replace("/auth/login?reason=idle_timeout");
  }
}

/**
 * หมด session เมื่อไม่มี interaction จากผู้ใช้จริงครบ 30 นาที
 *
 * localStorage ทำให้ activity จากแท็บหนึ่งต่ออายุแท็บอื่นของ Hub ด้วย ขณะที่
 * background polling/heartbeat ไม่แตะ timestamp นี้ จึงไม่นับเป็นการใช้งานจริง.
 */
export function IdleSessionGuard({
  timeoutMs = IDLE_TIMEOUT_MS,
  onExpire = revokeAndRedirect,
}: {
  timeoutMs?: number;
  onExpire?: () => Promise<void>;
}) {
  useEffect(() => {
    let expiring = false;
    let lastWrite = 0;

    const readLastActivity = () => {
      const value = Number(window.localStorage.getItem(ACTIVITY_KEY));
      return Number.isFinite(value) && value > 0 ? value : null;
    };

    const recordActivity = () => {
      if (expiring) return;
      const now = Date.now();
      if (now - lastWrite < ACTIVITY_WRITE_THROTTLE_MS) return;
      lastWrite = now;
      window.localStorage.setItem(ACTIVITY_KEY, String(now));
    };

    const expireSession = async () => {
      if (expiring) return;
      expiring = true;

      // Heartbeat ต้องหยุดก่อน revoke เพื่อไม่ให้ session ถูกนับว่า online ต่อ
      // ระหว่างที่คำขอ logout กำลังทำงาน.
      document.dispatchEvent(new Event("hub:idle-timeout"));
      window.localStorage.removeItem(ACTIVITY_KEY);
      window.localStorage.setItem(LOGOUT_KEY, String(Date.now()));

      await onExpire();
    };

    const checkIdle = () => {
      const lastActivity = readLastActivity();
      if (lastActivity === null) {
        recordActivity();
        return;
      }
      if (Date.now() - lastActivity >= timeoutMs) void expireSession();
    };

    const onStorage = (event: StorageEvent) => {
      // logout จากแท็บหนึ่งต้องปิด session ของทุกแท็บทันที
      if (event.key === LOGOUT_KEY && event.newValue) void expireSession();
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") checkIdle();
    };

    const activityEvents: Array<keyof DocumentEventMap> = [
      "mousemove",
      "keydown",
      "scroll",
      "click",
      "touchstart",
    ];
    for (const eventName of activityEvents) {
      document.addEventListener(eventName, recordActivity, { passive: true });
    }
    window.addEventListener("storage", onStorage);
    document.addEventListener("visibilitychange", onVisible);

    checkIdle();
    const timer = window.setInterval(checkIdle, CHECK_INTERVAL_MS);

    return () => {
      window.clearInterval(timer);
      for (const eventName of activityEvents) {
        document.removeEventListener(eventName, recordActivity);
      }
      window.removeEventListener("storage", onStorage);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [onExpire, timeoutMs]);

  return null;
}
