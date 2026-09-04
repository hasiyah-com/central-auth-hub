"use client";

/**
 * Sidebar — Signal Room layout
 *
 * โครงตามดีไซน์อ้างอิง: brand block (HUB / SECURITY CONTROL) → แถบสภาพแวดล้อม →
 * กลุ่มเมนู COMMAND / SECURITY / DEVELOPER พร้อมไอคอนเส้น
 *
 * คง logic เดิมครบ: mobile drawer, badge จำนวนแจ้งเตือนจริง, แยกเมนูตามสิทธิ์,
 * EnvChip อ่าน hostname จริง (ไม่ hardcode PRODUCTION)
 *
 * NavItem ยังมี `glyph` อยู่ เพราะ CommandPalette (⌘K) ใช้แสดงผลร่วมกัน
 */

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

export type IconKey =
  | "grid"
  | "activity"
  | "users"
  | "network"
  | "inbox"
  | "alert"
  | "brain"
  | "shield"
  | "ban"
  | "lifebuoy"
  | "file"
  | "bell"
  | "user"
  | "terminal"
  | "plus";

export type NavItem = {
  href: string;
  label: string;
  glyph: string;
  icon: IconKey;
  live?: boolean;
  /**
   * คำค้นไทยสำหรับ CommandPalette — label แสดงผลเป็นอังกฤษ
   * แต่ผู้ใช้ยังพิมพ์ไทยค้นเมนูได้เหมือนเดิม (ไม่ให้ ⌘K พังจากการเปลี่ยนภาษา)
   */
  keywords?: string;
};

const ADMIN_COMMAND: NavItem[] = [
  { href: "/dashboard", label: "Overview", keywords: "ภาพรวมระบบ แดชบอร์ด", glyph: "OV", icon: "grid" },
  { href: "/activity", label: "Activity", keywords: "การเข้าใช้งาน กิจกรรม", glyph: "RT", icon: "activity", live: true },
  { href: "/users", label: "Users", keywords: "ผู้ใช้งาน ผู้ใช้ รายชื่อ", glyph: "ID", icon: "users" },
  { href: "/subsystems", label: "Subsystems", keywords: "ระบบย่อย", glyph: "SS", icon: "network" },
  { href: "/pending-requests", label: "Approvals", keywords: "คำขอ อนุมัติ", glyph: "RQ", icon: "inbox" },
];

const ADMIN_SECURITY: NavItem[] = [
  { href: "/incidents", label: "Incidents", keywords: "เหตุการณ์เสี่ยง", glyph: "IN", icon: "alert" },
  { href: "/ml", label: "ML / Anomaly", keywords: "ความผิดปกติ", glyph: "ML", icon: "brain" },
  { href: "/api-alerts", label: "API Alerts", keywords: "แจ้งเตือน api", glyph: "AP", icon: "shield" },
  { href: "/ip-blacklist", label: "IP Blacklist", keywords: "บัญชีดำ ไอพี", glyph: "IP", icon: "ban" },
  { href: "/recovery-tickets", label: "Recovery", keywords: "คำขอกู้บัญชี กู้คืน", glyph: "RC", icon: "lifebuoy" },
  { href: "/audit", label: "Audit Log", keywords: "บันทึกตรวจสอบ", glyph: "AU", icon: "file" },
  { href: "/notifications", label: "Notifications", keywords: "แจ้งเตือน", glyph: "NT", icon: "bell" },
  { href: "/account", label: "My Account", keywords: "บัญชีของฉัน", glyph: "ME", icon: "user" },
];

/** รวมไว้ให้ CommandPalette ค้นหาได้ครบทุกเมนู */
export const ADMIN_NAV: NavItem[] = [...ADMIN_COMMAND, ...ADMIN_SECURITY];

export const DEV_NAV: NavItem[] = [
  { href: "/developer/subsystems", label: "My Subsystems", keywords: "ระบบของฉัน", glyph: "SS", icon: "terminal" },
  { href: "/developer/subsystems/new", label: "Register New", keywords: "ลงทะเบียนใหม่ สร้าง", glyph: "+", icon: "plus" },
  { href: "/developer/account", label: "My Account", keywords: "บัญชีของฉัน", glyph: "ME", icon: "user" },
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

/** ไอคอนเส้น 16px — stroke ตามสีข้อความปัจจุบัน */
function Icon({ name }: { name: IconKey }) {
  const p: Record<IconKey, React.ReactNode> = {
    grid: (
      <>
        <rect x="2.5" y="2.5" width="5" height="5" rx="1" />
        <rect x="10.5" y="2.5" width="5" height="5" rx="1" />
        <rect x="2.5" y="10.5" width="5" height="5" rx="1" />
        <rect x="10.5" y="10.5" width="5" height="5" rx="1" />
      </>
    ),
    activity: <polyline points="1.5,9 5,9 7,4 11,14 13,9 16.5,9" />,
    users: (
      <>
        <circle cx="6.5" cy="6" r="2.6" />
        <path d="M2 15c0-2.5 2-4.2 4.5-4.2S11 12.5 11 15" />
        <path d="M11.5 10.9c2 .3 3.5 1.9 3.5 4.1" />
        <circle cx="12.4" cy="6.4" r="2.1" />
      </>
    ),
    network: (
      <>
        <rect x="6.5" y="1.5" width="5" height="4" rx="1" />
        <rect x="1.5" y="12.5" width="4.5" height="4" rx="1" />
        <rect x="12" y="12.5" width="4.5" height="4" rx="1" />
        <path d="M9 5.5v3.5M3.75 12.5V9H14.25v3.5" />
      </>
    ),
    inbox: (
      <>
        <path d="M2 10.5h3.5l1 2h5l1-2H16" />
        <path d="M2 10.5 4 3h10l2 7.5v4a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1z" />
      </>
    ),
    alert: (
      <>
        <path d="M9 2.5 16.5 15H1.5z" />
        <path d="M9 7v3.5M9 12.8v.2" />
      </>
    ),
    brain: (
      <>
        <rect x="3.5" y="3.5" width="11" height="11" rx="3" />
        <path d="M7 7h4v4H7z" />
        <path d="M9 1.5v2M9 14.5v2M1.5 9h2M14.5 9h2" />
      </>
    ),
    shield: <path d="M9 1.8 15 4v5c0 3.6-2.5 6.3-6 7.2C5.5 15.3 3 12.6 3 9V4z" />,
    ban: (
      <>
        <circle cx="9" cy="9" r="6.8" />
        <path d="M4.2 4.2l9.6 9.6" />
      </>
    ),
    lifebuoy: (
      <>
        <circle cx="9" cy="9" r="6.8" />
        <circle cx="9" cy="9" r="2.6" />
        <path d="M4.2 4.2 7.2 7.2M10.8 10.8l3 3M13.8 4.2l-3 3M7.2 10.8l-3 3" />
      </>
    ),
    file: (
      <>
        <path d="M4 1.8h6l4 4v10.4H4z" />
        <path d="M10 1.8v4h4M6.5 9h5M6.5 12h5" />
      </>
    ),
    bell: (
      <>
        <path d="M4.5 7.5a4.5 4.5 0 0 1 9 0c0 3.2 1 4.5 1 4.5H3.5s1-1.3 1-4.5z" />
        <path d="M7.4 14.5a1.8 1.8 0 0 0 3.2 0" />
      </>
    ),
    user: (
      <>
        <circle cx="9" cy="6" r="3" />
        <path d="M3.5 15.5c0-3 2.5-5 5.5-5s5.5 2 5.5 5" />
      </>
    ),
    terminal: (
      <>
        <rect x="1.8" y="3" width="14.4" height="12" rx="1.5" />
        <path d="M5 7.5 7.5 9.8 5 12M9.5 12.3h3.5" />
      </>
    ),
    plus: <path d="M9 3.5v11M3.5 9h11" />,
  };
  return (
    <svg
      viewBox="0 0 18 18"
      className="h-[17px] w-[17px] shrink-0"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {p[name]}
    </svg>
  );
}

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
    return () => {
      document.body.style.overflow = "";
    };
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
      {/* brand */}
      <div className="px-5 pb-4 pt-5">
        <div className="flex items-center gap-3">
          <div className="relative grid h-11 w-11 place-items-center rounded-xl border border-brand-500/35 bg-brand-500/10 text-brand-500">
            <svg viewBox="0 0 18 18" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M6 3.2a2.2 2.2 0 1 0 0 4.4h6a2.2 2.2 0 1 1 0 4.4M6 7.6v6.6M12 7.6H6" />
            </svg>
            <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-brand-500 shadow-[0_0_10px_#34e8c4]" />
          </div>
          <div className="min-w-0">
            <div className="font-display text-lg font-bold leading-none text-white">HUB</div>
            <div className="mt-1 font-mono text-[9px] uppercase tracking-[.22em] text-ink-500">
              security control
            </div>
          </div>
          <button
            onClick={() => setOpen(false)}
            className="ml-auto grid h-9 w-9 place-items-center rounded-lg border border-white/10 text-ink-400 hover:bg-white/10 hover:text-white lg:hidden"
            aria-label="ปิดเมนู"
          >
            ×
          </button>
        </div>
      </div>

      <EnvChip />

      <nav className="flex-1 overflow-y-auto px-3 py-4">
        {isAdmin && (
          <>
            <NavGroup title="Command" items={ADMIN_COMMAND} pathname={pathname} badgeFor={badgeFor} />
            <div className="mt-5">
              <NavGroup
                title="Security"
                items={ADMIN_SECURITY}
                pathname={pathname}
                badgeFor={badgeFor}
              />
            </div>
          </>
        )}
        {isDeveloper && (
          <div className={isAdmin ? "mt-5" : ""}>
            <NavGroup title="Developer" items={DEV_NAV} pathname={pathname} badgeFor={badgeFor} />
          </div>
        )}
        {!me && (
          <div className="px-3 py-3 font-mono text-[10px] uppercase tracking-wider text-ink-500">
            Loading identity…
          </div>
        )}
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
      <button
        onClick={() => setOpen(true)}
        className="fixed left-3 top-3 z-30 grid h-10 w-10 place-items-center rounded-xl border border-ink-200 bg-white text-ink-800 shadow-sm lg:hidden"
        aria-label="เปิดเมนู"
        aria-expanded={open}
      >
        <span className="space-y-1">
          <i className="block h-px w-4 bg-current" />
          <i className="block h-px w-4 bg-current" />
          <i className="block h-px w-4 bg-current" />
        </span>
      </button>
      <div
        onClick={() => setOpen(false)}
        className={clsx(
          "fixed inset-0 z-40 bg-ink-900/55 backdrop-blur-sm transition-opacity lg:hidden",
          open ? "opacity-100" : "pointer-events-none opacity-0"
        )}
        aria-hidden="true"
      />
      <aside
        className={clsx(
          "fixed inset-y-0 left-0 z-50 flex w-[272px] flex-col overflow-hidden border-r border-white/[.08] bg-ink-900 text-ink-100 shadow-2xl transition-transform duration-300 lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 lg:shadow-none",
          open ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_10%_0%,rgba(52,232,196,.10),transparent_22rem)]" />
        <div className="relative flex min-h-0 flex-1 flex-col">{content}</div>
      </aside>
    </>
  );
}

function NavGroup({
  title,
  items,
  pathname,
  badgeFor,
}: {
  title: string;
  items: NavItem[];
  pathname: string;
  badgeFor: (href: string) => number | undefined;
}) {
  return (
    <div>
      <div className="mb-2 px-3 font-mono text-[9px] font-semibold uppercase tracking-[.2em] text-ink-500">
        {title}
      </div>
      <div className="space-y-0.5">
        {items.map((item) => (
          <NavLink key={item.href} {...item} pathname={pathname} badge={badgeFor(item.href)} />
        ))}
      </div>
    </div>
  );
}

function NavLink({
  href,
  label,
  icon,
  live,
  pathname,
  badge,
}: NavItem & { pathname: string; badge?: number }) {
  const exactDeveloperList = href === "/developer/subsystems";
  const active = pathname === href || (!exactDeveloperList && pathname.startsWith(href + "/"));
  return (
    <Link
      href={href}
      className={clsx(
        "group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-[13px] font-medium transition",
        active
          ? "bg-white/[.075] text-white"
          : "text-ink-400 hover:bg-white/[.045] hover:text-ink-100"
      )}
    >
      {active && (
        <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-brand-500 shadow-[0_0_10px_#34e8c4]" />
      )}
      <span className={active ? "text-brand-500" : "text-ink-500 group-hover:text-ink-300"}>
        <Icon name={icon} />
      </span>
      <span className="flex-1 truncate">{label}</span>
      {live && !badge && (
        <span className="rounded border border-brand-500/30 bg-brand-500/10 px-1.5 py-0.5 font-mono text-[8px] font-bold uppercase tracking-wider text-brand-500">
          live
        </span>
      )}
      {!!badge && badge > 0 && (
        <span className="min-w-5 rounded-full bg-rose-500 px-1.5 py-0.5 text-center font-mono text-[9px] font-semibold text-white">
          {badge > 99 ? "99+" : badge}
        </span>
      )}
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
    <div className="mx-4 mb-1 flex items-center gap-2.5 rounded-xl border border-white/[.08] bg-white/[.03] px-3 py-2.5">
      <span
        className={clsx(
          "h-1.5 w-1.5 shrink-0 rounded-full",
          isLocal ? "bg-amber-400" : "bg-brand-500 shadow-[0_0_8px_#34e8c4]"
        )}
      />
      <span className="font-mono text-[10px] font-semibold uppercase tracking-[.14em] text-white">
        {isLocal ? "local" : "deployed"}
      </span>
      <span className="ml-auto min-w-0 truncate font-mono text-[9px] text-ink-500" title={host}>
        {host}
      </span>
    </div>
  );
}
