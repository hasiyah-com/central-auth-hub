"use client";

// useSearchParams() ต้อง render ตอน request time — กัน prerender error ตอน next build
export const dynamic = "force-dynamic";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

function CallbackInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  // กัน React StrictMode รัน effect ซ้ำใน dev (2x mount) — ใช้ ref guard
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;

    const token = params.get("token");
    if (!token) {
      setError("ไม่ได้รับ token จาก Hub — กรุณา login ใหม่");
      return;
    }

    (async () => {
      try {
        // 1) ลบ cookie เก่าออกก่อน (กัน admin cookie ติดมาแล้ว set ทับไม่ได้)
        await fetch("/api/set-token", {
          method: "DELETE",
          credentials: "include",
        }).catch(() => null);

        // 2) Set cookie ใหม่จาก token ใน URL
        const setRes = await fetch("/api/set-token", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ token }),
        });
        if (!setRes.ok) {
          const body = await setRes.json().catch(() => ({}));
          throw new Error(body.error || `set-token failed: ${setRes.status}`);
        }

        // 3) ลบ token ออกจาก URL (history hygiene)
        window.history.replaceState({}, "", "/auth/callback");

        // 4) อ่าน profile → route ตาม role
        const me = await fetch("/api/me", { credentials: "include" })
          .then((r) => (r.ok ? r.json() : null))
          .catch(() => null);

        const isAdmin =
          me?.is_hub_admin === true || me?.user_type === "admin";
        const dest = isAdmin ? "/dashboard" : "/developer/subsystems";

        // ใช้ window.location.href แทน router.replace
        // เพื่อ full reload — กัน RSC cache ของ middleware เก่า
        window.location.href = dest;
      } catch (e) {
        const err = e as { message?: string };
        setError(err.message || "set-token failed");
        ran.current = false; // ให้ retry ได้ถ้ากดใหม่
      }
    })();
  }, [params, router]);

  return (
    <main className="min-h-screen grid place-items-center bg-ink-50">
      <div className="text-center">
        {error ? (
          <div className="space-y-4">
            <div className="text-red-600 font-semibold">{error}</div>
            <a
              href="/auth/login"
              className="inline-block px-4 py-2 rounded-lg bg-brand-600 text-white text-sm"
            >
              กลับไปหน้า login
            </a>
          </div>
        ) : (
          <div className="flex items-center gap-3 text-ink-500">
            <div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
            <span>กำลังเข้าสู่ระบบ…</span>
          </div>
        )}
      </div>
    </main>
  );
}

export default function CallbackPage() {
  return (
    <Suspense fallback={null}>
      <CallbackInner />
    </Suspense>
  );
}
