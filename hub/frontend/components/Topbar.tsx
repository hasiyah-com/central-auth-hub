"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

type Me = {
  email: string;
  full_name: string | null;
  user_type: string | null;
  faculty: string | null;
  is_hub_admin: boolean;
};

export function Topbar({ title }: { title: string }) {
  const [me, setMe] = useState<Me | null>(null);
  const router = useRouter();

  useEffect(() => {
    fetch("/api/me", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  async function logout() {
    await fetch("/api/set-token", { method: "DELETE", credentials: "include" });
    router.push("/auth/login");
  }

  const initial = (me?.full_name || me?.email || "?").charAt(0).toUpperCase();

  return (
    <header className="bg-white border-b border-ink-200 px-8 py-4 flex items-center justify-between sticky top-0 z-10">
      <div>
        <h1 className="text-xl font-extrabold text-ink-900">{title}</h1>
      </div>
      <div className="flex items-center gap-4">
        {me && (
          <div className="flex items-center gap-3">
            <div className="text-right hidden sm:block">
              <div className="text-sm font-semibold text-ink-900 leading-tight">
                {me.full_name || me.email}
              </div>
              <div className="text-[11px] text-ink-500">
                {me.email}
                {me.is_hub_admin && (
                  <span className="ml-2 px-1.5 py-0.5 rounded bg-brand-50 text-brand-700 text-[10px] font-bold">
                    ADMIN
                  </span>
                )}
              </div>
            </div>
            <div className="w-9 h-9 rounded-full bg-gradient-to-br from-brand-500 to-brand-700 grid place-items-center text-white text-sm font-bold">
              {initial}
            </div>
          </div>
        )}
        <button
          onClick={logout}
          className="px-3 py-1.5 rounded-lg text-sm font-medium text-ink-600 hover:bg-ink-100 transition"
        >
          ออกจากระบบ
        </button>
      </div>
    </header>
  );
}
