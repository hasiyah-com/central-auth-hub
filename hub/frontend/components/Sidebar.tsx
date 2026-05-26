"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

const NAV = [
  { href: "/dashboard", label: "ภาพรวม", icon: "📊" },
  { href: "/users", label: "ผู้ใช้งาน", icon: "👥" },
  { href: "/subsystems", label: "ระบบย่อย", icon: "🧩" },
  { href: "/audit", label: "Audit Log", icon: "📜" },
];

export function Sidebar() {
  const pathname = usePathname();
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
            <div className="text-sm font-bold text-white">Admin Console</div>
          </div>
        </div>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV.map((item) => {
          const active = pathname === item.href || pathname.startsWith(item.href + "/");
          return (
            <Link
              key={item.href}
              href={item.href}
              className={clsx(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition",
                active
                  ? "bg-brand-600 text-white shadow-lg shadow-brand-900/40"
                  : "text-ink-300 hover:bg-ink-800 hover:text-white"
              )}
            >
              <span className="text-base">{item.icon}</span>
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="px-5 py-4 border-t border-ink-800 text-[11px] text-ink-500">
        <div>v0.5.0 · Week 8</div>
        <div className="text-ink-600 mt-1">OAuth · JWT · RBAC</div>
      </div>
    </aside>
  );
}
