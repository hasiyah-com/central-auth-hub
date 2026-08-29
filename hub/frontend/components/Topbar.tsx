"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

type Me = {
  email: string;
  full_name: string | null;
  user_type: string | null;
  faculty: string | null;
  is_hub_admin: boolean;
};

function avatarColor(value: string) {
  let hash = 0;
  for (let i = 0; i < value.length; i++) hash = value.charCodeAt(i) + ((hash << 5) - hash);
  return `hsl(${Math.abs(hash) % 360} 58% 42%)`;
}

export function Topbar({ title }: { title: string }) {
  const [me, setMe] = useState<Me | null>(null);
  const router = useRouter();
  const pathname = usePathname();

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

  const identity = me?.full_name || me?.email || "?";
  const initial = identity.charAt(0).toUpperCase();
  const color = useMemo(() => avatarColor(me?.email || identity), [me?.email, identity]);
  const crumb = pathname.split("/").filter(Boolean).join(" / ") || "dashboard";

  return (
    <header className="sticky top-0 z-20 flex min-h-[68px] items-center border-b border-ink-200/90 bg-white/90 px-4 pl-16 backdrop-blur-xl sm:px-6 sm:pl-16 lg:px-8">
      <div className="min-w-0">
        <div className="truncate font-mono text-[9px] uppercase tracking-[.18em] text-ink-400">hub / {crumb}</div>
        <h1 className="truncate font-display text-lg font-bold text-ink-900 sm:text-xl">{title}</h1>
      </div>
      <div className="ml-auto flex items-center gap-3">
        {me && (
          <div className="flex items-center gap-3 rounded-xl border border-ink-200 bg-white px-2 py-1.5">
            <div className="hidden text-right md:block">
              <div className="max-w-48 truncate text-xs font-semibold text-ink-900">{identity}</div>
              <div className="max-w-48 truncate font-mono text-[9px] text-ink-500">{me.email}</div>
            </div>
            <div className="grid h-8 w-8 place-items-center rounded-lg text-xs font-bold text-white" style={{ backgroundColor: color }}>{initial}</div>
          </div>
        )}
        <button onClick={logout} className="rounded-lg border border-transparent px-3 py-2 text-xs font-semibold text-ink-500 hover:border-ink-200 hover:bg-white hover:text-ink-900">ออกจากระบบ</button>
      </div>
    </header>
  );
}
