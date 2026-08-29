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

export type NavItem = { href: string; label: string; glyph: string };

export const ADMIN_NAV: NavItem[] = [
  { href: "/dashboard", label: "ภาพรวม", glyph: "OV" },
  { href: "/activity", label: "การเข้าใช้งาน", glyph: "RT" },
  { href: "/incidents", label: "เหตุการณ์เสี่ยง", glyph: "IN" },
  { href: "/notifications", label: "แจ้งเตือน", glyph: "NT" },
  { href: "/users", label: "ผู้ใช้งาน", glyph: "ID" },
  { href: "/subsystems", label: "ระบบย่อย", glyph: "SS" },
  { href: "/pending-requests", label: "คำขอ Approve", glyph: "RQ" },
  { href: "/recovery-tickets", label: "คำขอกู้บัญชี", glyph: "RC" },
  { href: "/ml", label: "ML / ความผิดปกติ", glyph: "ML" },
  { href: "/api-alerts", label: "API Alerts", glyph: "AP" },
  { href: "/ip-blacklist", label: "IP Blacklist", glyph: "IP" },
  { href: "/audit", label: "Audit Log", glyph: "AU" },
  { href: "/account", label: "บัญชีของฉัน", glyph: "ME" },
];

export const DEV_NAV: NavItem[] = [
  { href: "/developer/subsystems", label: "ระบบของฉัน", glyph: "SS" },
  { href: "/developer/subsystems/new", label: "ลงทะเบียนใหม่", glyph: "+" },
  { href: "/developer/account", label: "บัญชีของฉัน", glyph: "ME" },
];

type NotifCount = {
  total: number;
  unread?: number;
  unread_by_category?: {
    approval_requests?: number;
    ml_anomaly?: number;
    api_alerts?: number;
  };
};

export function Sidebar() {
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [notif, setNotif] = useState<NotifCount | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    fetch("/api/me", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  useEffect(() => {
    if (!me?.is_hub_admin) return;
    const fetchCount = () =>
      fetch("/api/proxy/admin/notifications/count", { credentials: "include" })
        .then((r) => (r.ok ? r.json() : null))
        .then(setNotif)
        .catch(() => undefined);
    fetchCount();
    const timer = setInterval(fetchCount, 30_000);
    return () => clearInterval(timer);
  }, [me]);

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => { document.body.style.overflow = ""; };
  }, [open]);

  const isAdmin = me?.is_hub_admin === true || me?.user_type === "admin";
  const isDeveloper = ["teacher", "staff", "admin"].includes(me?.user_type || "");
  const unread = notif?.unread_by_category || {};
  const badgeFor = (href: string) => {
    if (href === "/notifications") return notif?.unread ?? notif?.total;
    if (href === "/pending-requests") return unread.approval_requests;
    if (href === "/ml") return unread.ml_anomaly;
    if (href === "/api-alerts") return unread.api_alerts;
    return undefined;
  };

  const content = (
    <>
      <div className="border-b border-white/[.08] px-5 py-5">
        <div className="flex items-center gap-3">
          <div className="relative grid h-10 w-10 place-items-center rounded-xl border border-brand-500/30 bg-brand-500/10 font-mono text-sm font-semibold text-brand-500">
            H
            <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-brand-500 shadow-[0_0_10px_#34e8c4]" />
          </div>
          <div className="min-w-0">
            <div className="font-mono text-[9px] uppercase tracking-[.22em] text-ink-400">Signal Room</div>
            <div className="font-display text-[15px] font-bold text-white">Central Auth Hub</div>
          </div>
          <button onClick={() => setOpen(false)} className="ml-auto grid h-9 w-9 place-items-center rounded-lg border border-white/10 text-ink-400 hover:bg-white/10 hover:text-white lg:hidden" aria-label="ปิดเมนู">×</button>
        </div>
      </div>

      <EnvChip />
      <nav className="flex-1 overflow-y-auto px-3 py-4">
        {isAdmin && (
          <NavGroup title="Admin Console" items={ADMIN_NAV} pathname={pathname} badgeFor={badgeFor} />
        )}
        {isDeveloper && (
          <div className={isAdmin ? "mt-4 border-t border-white/[.08] pt-4" : ""}>
            <NavGroup title="Developer Portal" items={DEV_NAV} pathname={pathname} badgeFor={badgeFor} />
          </div>
        )}
        {!me && <div className="px-3 py-3 font-mono text-[10px] uppercase tracking-wider text-ink-500">Loading identity…</div>}
      </nav>

      <div className="border-t border-white/[.08] px-5 py-4">
        <div className="flex items-center gap-2 font-mono text-[9px] uppercase tracking-[.16em] text-ink-500">
          <span className="signal-dot !h-1.5 !w-1.5" />
          systems monitored
        </div>
        <div className="mt-2 font-mono text-[9px] text-ink-600">OAuth 2.0 · OIDC · RBAC · RBA</div>
      </div>
    </>
  );

  return (
    <>
      <button onClick={() => setOpen(true)} className="fixed left-3 top-3 z-30 grid h-10 w-10 place-items-center rounded-xl border border-ink-200 bg-white text-ink-800 shadow-sm lg:hidden" aria-label="เปิดเมนู" aria-expanded={open}>
        <span className="space-y-1"><i className="block h-px w-4 bg-current" /><i className="block h-px w-4 bg-current" /><i className="block h-px w-4 bg-current" /></span>
      </button>
      <div onClick={() => setOpen(false)} className={clsx("fixed inset-0 z-40 bg-ink-900/55 backdrop-blur-sm transition-opacity lg:hidden", open ? "opacity-100" : "pointer-events-none opacity-0")} aria-hidden="true" />
      <aside className={clsx("fixed inset-y-0 left-0 z-50 flex w-[272px] flex-col overflow-hidden border-r border-white/[.08] bg-ink-900 text-ink-100 shadow-2xl transition-transform duration-300 lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 lg:shadow-none", open ? "translate-x-0" : "-translate-x-full")}>
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_10%_0%,rgba(52,232,196,.10),transparent_22rem)]" />
        <div className="relative flex min-h-0 flex-1 flex-col">{content}</div>
      </aside>
    </>
  );
}

function NavGroup({ title, items, pathname, badgeFor }: { title: string; items: NavItem[]; pathname: string; badgeFor: (href: string) => number | undefined }) {
  return (
    <div>
      <div className="mb-2 px-3 font-mono text-[9px] font-semibold uppercase tracking-[.2em] text-ink-500">{title}</div>
      <div className="space-y-1">
        {items.map((item) => <NavLink key={item.href} {...item} pathname={pathname} badge={badgeFor(item.href)} />)}
      </div>
    </div>
  );
}

function NavLink({ href, label, glyph, pathname, badge }: NavItem & { pathname: string; badge?: number }) {
  const exactDeveloperList = href === "/developer/subsystems";
  const active = pathname === href || (!exactDeveloperList && pathname.startsWith(href + "/"));
  return (
    <Link href={href} className={clsx("group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-[13px] font-medium transition", active ? "bg-white/[.075] text-white" : "text-ink-400 hover:bg-white/[.045] hover:text-ink-100")}>
      {active && <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-brand-500 shadow-[0_0_10px_#34e8c4]" />}
      <span className={clsx("grid h-7 w-7 place-items-center rounded-md border font-mono text-[9px] font-semibold", active ? "border-brand-500/35 bg-brand-500/10 text-brand-500" : "border-white/[.08] text-ink-500 group-hover:border-white/[.15] group-hover:text-ink-300")}>{glyph}</span>
      <span className="flex-1 truncate">{label}</span>
      {!!badge && badge > 0 && <span className="min-w-5 rounded-full bg-rose-500 px-1.5 py-0.5 text-center font-mono text-[9px] font-semibold text-white">{badge > 99 ? "99+" : badge}</span>}
    </Link>
  );
}

/**
 * แถบบอก "console นี้ถูกเสิร์ฟจากที่ไหน" — อ่าน hostname จริงฝั่ง client
 * ไม่ hardcode คำว่า PRODUCTION เพราะโปรเจกต์ยังไม่มี env var สำหรับ environment
 * (localhost / 127.0.0.1 / *.local = local, นอกนั้น = deployed)
 */
function EnvChip() {
  const [host, setHost] = useState<string | null>(null);
  useEffect(() => setHost(window.location.host), []);
  if (!host) return null;
  const isLocal = /^(localhost|127\.0\.0\.1|\[::1\])(:|$)|\.local(:|$)/.test(host);
  return (
    <div className="flex items-center gap-2 border-b border-white/[.08] px-5 py-3">
      <span
        className={clsx(
          "rounded-md border px-2 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-[.14em]",
          isLocal
            ? "border-amber-400/30 bg-amber-400/10 text-amber-300"
            : "border-brand-500/30 bg-brand-500/10 text-brand-500"
        )}
      >
        {isLocal ? "local" : "deployed"}
      </span>
      <span className="min-w-0 truncate font-mono text-[9px] text-ink-500" title={host}>
        {host}
      </span>
    </div>
  );
}
