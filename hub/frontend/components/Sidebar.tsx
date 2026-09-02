"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

type Me = { email: string; full_name: string | null; user_type: string | null; is_hub_admin: boolean };
export type NavItem = { href: string; label: string; glyph: string };

export const ADMIN_NAV: NavItem[] = [
  { href: "/dashboard", label: "ภาพรวมระบบ", glyph: "OV" },
  { href: "/activity", label: "การเข้าใช้งาน", glyph: "RT" },
  { href: "/users", label: "ผู้ใช้งาน", glyph: "ID" },
  { href: "/subsystems", label: "ระบบย่อย", glyph: "SS" },
  { href: "/incidents", label: "เหตุการณ์เสี่ยง", glyph: "IN" },
  { href: "/ml", label: "ML / ความผิดปกติ", glyph: "ML" },
  { href: "/api-alerts", label: "API Alerts", glyph: "AP" },
  { href: "/ip-blacklist", label: "IP Blacklist", glyph: "IP" },
  { href: "/recovery-tickets", label: "คำขอกู้บัญชี", glyph: "RC" },
  { href: "/audit", label: "Audit Log", glyph: "AU" },
  { href: "/notifications", label: "แจ้งเตือน", glyph: "NT" },
  { href: "/pending-requests", label: "คำขออนุมัติ", glyph: "RQ" },
  { href: "/account", label: "บัญชีของฉัน", glyph: "ME" },
];

export const DEV_NAV: NavItem[] = [
  { href: "/developer/subsystems", label: "ระบบของฉัน", glyph: "DV" },
  { href: "/developer/subsystems/new", label: "ลงทะเบียนใหม่", glyph: "+" },
  { href: "/developer/account", label: "บัญชีของฉัน", glyph: "ME" },
];

type NotifCount = { total: number; unread?: number; unread_by_category?: { approval_requests?: number; ml_anomaly?: number; api_alerts?: number } };

const GROUPS = [
  { title: "COMMAND", glyphs: new Set(["OV", "RT", "ID", "SS"]) },
  { title: "SECURITY", glyphs: new Set(["IN", "ML", "AP", "IP", "RC", "AU", "NT"]) },
  { title: "DEVELOPER", glyphs: new Set(["RQ", "ME"]) },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [notif, setNotif] = useState<NotifCount | null>(null);

  useEffect(() => {
    fetch("/api/me", { credentials: "include" }).then((r) => (r.ok ? r.json() : null)).then(setMe).catch(() => setMe(null));
  }, []);

  useEffect(() => {
    if (!me?.is_hub_admin) return;
    const load = () => fetch("/api/proxy/admin/notifications/count", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null)).then(setNotif).catch(() => undefined);
    load();
    const timer = setInterval(load, 30_000);
    return () => clearInterval(timer);
  }, [me]);

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

  async function logout() {
    await fetch("/api/set-token", { method: "DELETE", credentials: "include" });
    router.push("/auth/login");
  }

  const identity = me?.full_name || me?.email || "กำลังโหลด";
  const initials = useMemo(() => identity.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase(), [identity]);

  return (
    <aside className="sidebar">
      <Link href="/dashboard" className="brand-lockup">
        <div className="brand-icon"><SignalIcon type="HUB" /><Signal /></div>
        <div><strong>HUB</strong><span>SECURITY CONTROL</span></div>
      </Link>
      <Environment />
      <nav aria-label="เมนูหลัก">
        {isAdmin && GROUPS.map((group, index) => {
          const items = ADMIN_NAV.filter((item) => group.glyphs.has(item.glyph));
          return <div key={group.title}><p className={`nav-group ${index ? "divided" : ""}`}>{group.title}</p>{items.map((item) => <NavLink key={item.href} item={item} pathname={pathname} badge={badgeFor(item.href)} />)}</div>;
        })}
        {isDeveloper && !isAdmin && <div><p className="nav-group">DEVELOPER</p>{DEV_NAV.map((item) => <NavLink key={item.href} item={item} pathname={pathname} />)}</div>}
      </nav>
      <div className="sidebar-foot">
        <div className="operator"><div className="avatar">{initials || "?"}</div><div><strong>{identity}</strong><span>{me?.is_hub_admin ? "Super Admin" : me?.user_type || "Identity"}</span></div><SignalIcon type="SET" /></div>
        <button type="button" className="logout" onClick={logout}><SignalIcon type="OUT" />ออกจากระบบ</button>
      </div>
    </aside>
  );
}

function NavLink({ item, pathname, badge }: { item: NavItem; pathname: string; badge?: number }) {
  const active = pathname === item.href || pathname.startsWith(item.href + "/");
  return <Link href={item.href} className={`nav-link ${active ? "active" : ""}`}><SignalIcon type={item.glyph} /><span>{item.label}</span>{!!badge && badge > 0 && <b className="nav-alert">{badge > 99 ? "99+" : badge}</b>}{item.href === "/activity" && <b className="nav-live">LIVE</b>}</Link>;
}

function Environment() {
  const [host, setHost] = useState("");
  useEffect(() => setHost(window.location.host), []);
  const local = /^(localhost|127\.0\.0\.1|\[::1\])(:|$)|\.local(:|$)/.test(host);
  return <div className="environment"><Signal /><span>{local ? "LOCAL" : "PRODUCTION"}</span><b className="mono">{host || "CONNECTING"}</b></div>;
}

function Signal() { return <span className="signal-dot" aria-hidden="true"><i /></span>; }

function SignalIcon({ type }: { type: string }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  let body: React.ReactNode;
  switch (type) {
    case "OV": body = <><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="4"/><rect x="14" y="11" width="7" height="10"/><rect x="3" y="14" width="7" height="7"/></>; break;
    case "RT": body = <><path d="M3 12h4l2-6 4 12 2-6h6"/><path d="M4 4v16M20 4v16" opacity=".35"/></>; break;
    case "ID": case "ME": body = <><circle cx="12" cy="8" r="4"/><path d="M4 21c.7-4 3.3-6 8-6s7.3 2 8 6"/></>; break;
    case "SS": body = <><rect x="3" y="4" width="7" height="7"/><rect x="14" y="4" width="7" height="7"/><rect x="3" y="15" width="7" height="6"/><rect x="14" y="15" width="7" height="6"/></>; break;
    case "IN": body = <><path d="M12 3 2.8 20h18.4L12 3Z"/><path d="M12 9v5M12 17.5v.1"/></>; break;
    case "ML": body = <><path d="M8 5a4 4 0 0 0-4 4v6a4 4 0 0 0 4 4M16 5a4 4 0 0 1 4 4v6a4 4 0 0 1-4 4M8 3v18M16 3v18M8 8h4M12 16h4"/></>; break;
    case "AP": body = <><path d="M12 2.8 20 6v5.5c0 5-3.1 8.1-8 9.7-4.9-1.6-8-4.7-8-9.7V6l8-3.2Z"/><path d="m8.5 12 2.2 2.2 4.8-5"/></>; break;
    case "IP": body = <><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/></>; break;
    case "RC": body = <><circle cx="8" cy="12" r="4"/><path d="M12 12h9M18 12v3M15 12v2"/></>; break;
    case "AU": body = <><path d="M6 3h9l4 4v14H6z"/><path d="M15 3v5h4M9 12h6M9 16h6"/></>; break;
    case "NT": body = <><path d="M5 17h14l-2-3V9a5 5 0 0 0-10 0v5l-2 3Z"/><path d="M10 20h4"/></>; break;
    case "RQ": case "DV": body = <><circle cx="6" cy="6" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="12" cy="18" r="2"/><path d="M8 6h8M7 8l4 8M17 8l-4 8"/></>; break;
    case "+": body = <path d="M12 5v14M5 12h14"/>; break;
    case "SET": body = <><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1"/></>; break;
    case "OUT": body = <><path d="M10 5H4v14h6M14 8l4 4-4 4M8 12h10"/></>; break;
    default: body = <><circle cx="12" cy="12" r="8"/><path d="M8 12h8M12 8v8"/></>;
  }
  return <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" {...common}>{body}</svg>;
}
