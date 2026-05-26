"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

export default function CallbackPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = params.get("token");
    if (!token) {
      setError("ไม่ได้รับ token จาก Hub — กรุณา login ใหม่");
      return;
    }

    // POST token → /api/set-token → set httpOnly cookie → redirect
    fetch("/api/set-token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    })
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.error || `set-token failed: ${res.status}`);
        }
        // ลบ token ออกจาก URL ก่อน redirect (เผื่อ history)
        window.history.replaceState({}, "", "/auth/callback");
        router.replace("/dashboard");
      })
      .catch((e) => setError(e.message));
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
