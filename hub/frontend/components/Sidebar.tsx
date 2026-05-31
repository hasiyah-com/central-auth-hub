"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import clsx from "clsx";

type Me = {
  email: string;
  full_name: string | null;
  user_type: string | null;
  is_hub_admin: boolean;
};

const ADMIN_NAV = [
  { href: "/dashboard", label: "ภาพรวม", icon: "📊" },
  { href: "/users", label: "ผู้ใช้งาน", icon: "👥" },
  { href: "/subsystems", label: "ระบบย่อย", icon: "🧩" },
  { href: "/ml", label: "ML / ความผิดปกติ", icon: "🧠" },
  { href: "/api-alerts", label: "API Alerts", icon: "🛡️" },
  { href: "/ip-blacklist", label: "IP Blacklist", icon: "🚫" },
  { href: "/audit", label: "Audit Log", icon: "📜" },
];

const DEV_NAV = [
  { href: "/developer/subsystems", label: "ระบบของฉัน", icon: "🛠️" },
  { href: "/developer/subsystems/new", label: "ลงทะเบียนใหม่", icon: "➕" },
];

export function Sidebar() {
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    fetch("/api/me", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  const isAdmin = me?.is_hub_admin === true || me?.user_type === "admin";
  const isDeveloper =
    me?.user_type === "teacher" ||
    me?.user_type === "staff" ||
    me?.user_type === "admin";

  return (
    <aside className="w-60 bg-ink-900 text-ink-100 flex flex-col h-screen sticky top-0">
      <div className="px-5 py-6 border-b border-ink-800">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 grid place-items-center text-white text-lg font-bold">
            H
          </div>
          <div>
            <div className="text-[10px] text-ink-400 font-semibold uppercase tracking-wider">
              Central Auth
            </div>
            <div className="text-sm font-bold text-white">Hub Portal</div>
          </div>
        </div>
      </div>

      <nav className="flex-1 px-3 py-4 overflow-y-auto">
        {/* Admin section */}
        {isAdmin && (
          <div className="mb-4">
            <SectionLabel>Admin Console</SectionLabel>
            <div className="space-y-1">
              {ADMIN_NAV.map((item) => (
                <NavLink key={item.href} {...item} pathname={pathname} />
              ))}
            </div>
          </div>
        )}

        {/* Developer section */}
        {isDeveloper && (
          <div className={isAdmin ? "pt-3 border-t border-ink-800" : ""}>
            <SectionLabel>Developer Portal</SectionLabel>
            <div className="space-y-1">
              {DEV_NAV.map((item) => (
                <NavLink key={item.href} {...item} pathname={pathname} />
              ))}
            </div>
          </div>
        )}

        {/* Not signed in / no role */}
        {!me && (
          <div className="text-[11px] text-ink-500 px-3 py-2">กำลังโหลด…</div>
        )}
      </nav>

      <div className="px-5 py-4 border-t border-ink-800 text-[11px] text-ink-500">
        <div>v0.5.0 · Week 8</div>
        <div className="text-ink-600 mt-1">OAuth · JWT · RBAC</div>
      </div>
    </aside>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10px] font-bold uppercase tracking-widest text-ink-500 px-3 mb-2">
      {children}
    </div>
  );
}

function NavLink({
  href,
  label,
  icon,
  pathname,
}: {
  href: string;
  label: string;
  icon: string;
  pathname: string;
}) {
  // exact match for /developer/subsystems/new (don't bleed into list)
  // otherwise prefix match
  const active =
    pathname === href ||
    (href !== "/developer/subsystems" && pathname.startsWith(href + "/")) ||
    (href === "/developer/subsystems" &&
      pathname === "/developer/subsystems") ||
    (href === "/developer/subsystems" &&
      pathname.startsWith("/developer/subsystems/") &&
      !pathname.endsWith("/new"));
  return (
    <Link
      href={href}
      className={clsx(
        "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition",
        active
          ? "bg-brand-600 text-white shadow-lg shadow-brand-900/40"
          : "text-ink-300 hover:bg-ink-800 hover:text-white"
      )}
    >
      <span className="text-base">{icon}</span>
      <span>{label}</span>
    </Link>
  );
}
