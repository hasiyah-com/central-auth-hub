"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { Badge } from "@/components/Badge";
import { clientFetch } from "@/lib/api";

type NotifItem = {
  id: string;
  title: string;
  subtitle: string;
  created_at: string | null;
  severity: "warning" | "critical" | "info";
  meta: Record<string, unknown>;
  is_read: boolean;
};

type Category = {
  label: string;
  icon: string;
  count: number;
  items: NotifItem[];
  link: string;
};

type NotificationsResponse = {
  total: number;
  unread_in_view?: number;
  categories: Record<string, Category>;
};

type FlatItem = NotifItem & {
  categoryKey: string;
  categoryLabel: string;
  categoryIcon: string;
  link: string;
};

const SEVERITY_TONE: Record<string, "warn" | "danger" | "default"> = {
  warning: "warn",
  critical: "danger",
  info: "default",
};

const SEVERITY_BG: Record<string, string> = {
  critical: "bg-rose-50",
  warning: "bg-amber-50",
  info: "bg-blue-50",
};

const SEVERITY_ICON: Record<string, string> = {
  critical: "🚨",
  warning: "⚠️",
  info: "ℹ️",
};

function parseUTC(iso: string): Date {
  const hasTz = /[+-]\d{2}:?\d{2}$|Z$/i.test(iso);
  return new Date(hasTz ? iso : iso + "Z");
}

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const d = parseUTC(iso);
  const diffSec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  return parseUTC(iso).toLocaleString("th-TH", {
    timeZone: "Asia/Bangkok",
    dateStyle: "short",
    timeStyle: "short",
  });
}

const categoryOrder = [
  "approval_requests",
  "admin_overrides",
  "ml_anomaly",
  "api_alerts",
  "subsystem_health",
];

type ReadFilter = "all" | "unread" | "read";

export default function NotificationsPage() {
  const [data, setData] = useState<NotificationsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState<string>("all");
  const [readFilter, setReadFilter] = useState<ReadFilter>("all");
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    clientFetch<NotificationsResponse>("/admin/notifications")
      .then(setData)
      .catch((e) => setError(e.detail || "โหลดไม่สำเร็จ"))
      .finally(() => setLoading(false));
  }, []);

  async function markRead(category: string, id: string) {
    setBusy(`${category}:${id}`);
    try {
      await clientFetch("/admin/notifications/mark-read", {
        method: "POST",
        body: JSON.stringify({ items: [{ category, id }] }),
      });
      load();
    } catch {
      // silent
    } finally {
      setBusy(null);
    }
  }

  async function markUnread(category: string, id: string) {
    setBusy(`${category}:${id}`);
    try {
      await clientFetch("/admin/notifications/mark-unread", {
        method: "POST",
        body: JSON.stringify({ items: [{ category, id }] }),
      });
      load();
    } catch {
      // silent
    } finally {
      setBusy(null);
    }
  }

  async function clearAll() {
    if (!confirm("Mark ทั้งหมดว่าอ่านแล้ว?")) return;
    setBusy("clear");
    try {
      await clientFetch("/admin/notifications/clear-all", { method: "POST" });
      load();
    } catch {
      // silent
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, [load]);

  // Flatten ทุก category → 1 list สำหรับ table — เรียงเวลาล่าสุดก่อน
  const flatItems: FlatItem[] = useMemo(() => {
    if (!data) return [];
    const out: FlatItem[] = [];
    for (const key of categoryOrder) {
      const cat = data.categories[key];
      if (!cat) continue;
      for (const item of cat.items) {
        out.push({
          ...item,
          categoryKey: key,
          categoryLabel: cat.label,
          categoryIcon: cat.icon,
          link: cat.link,
        });
      }
    }
    out.sort((a, b) => {
      if (!a.created_at) return 1;
      if (!b.created_at) return -1;
      return parseUTC(b.created_at).getTime() - parseUTC(a.created_at).getTime();
    });
    return out;
  }, [data]);

  const filteredItems = useMemo(() => {
    let arr = flatItems;
    if (activeFilter !== "all") {
      arr = arr.filter((x) => x.categoryKey === activeFilter);
    }
    if (readFilter === "unread") {
      arr = arr.filter((x) => !x.is_read);
    } else if (readFilter === "read") {
      arr = arr.filter((x) => x.is_read);
    }
    return arr;
  }, [flatItems, activeFilter, readFilter]);

  const unreadCount = useMemo(
    () => flatItems.filter((x) => !x.is_read).length,
    [flatItems]
  );
  const readCount = flatItems.length - unreadCount;

  // Featured card — แสดงเฉพาะถ้ายังมี unread (อ่านหมด = ไม่ต้องเตือน)
  const featured = useMemo(() => {
    const unreadOnly = flatItems.filter((x) => !x.is_read);
    if (unreadOnly.length === 0) return null;
    const critical = unreadOnly.find((x) => x.severity === "critical");
    return critical || unreadOnly[0];
  }, [flatItems]);

  return (
    <>
      <Topbar title="แจ้งเตือนทั้งหมด" />
      <main className="p-8 max-w-7xl mx-auto w-full space-y-5">
        {/* Header */}
        <div className="flex items-end justify-between gap-3 flex-wrap">
          <div>
            <h2 className="text-sm font-bold text-ink-500 uppercase tracking-wider">
              Notification Center
            </h2>
            <p className="text-xs text-ink-400 mt-1">
              เรียงเวลาล่าสุด · auto-refresh 30s · มีทั้งหมด {data?.total ?? 0} รายการ
            </p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {data && (
              <div
                className={
                  "px-4 py-2 rounded-lg text-sm font-bold tabular-nums " +
                  (unreadCount > 0
                    ? "bg-amber-500 text-white"
                    : "bg-emerald-500 text-white")
                }
              >
                {unreadCount > 0
                  ? `🔔 ${unreadCount} ยังไม่อ่าน`
                  : "✓ อ่านครบแล้ว"}
              </div>
            )}
            {unreadCount > 0 && (
              <button
                onClick={clearAll}
                disabled={busy === "clear"}
                className="px-3 py-2 rounded-lg border border-emerald-300 hover:bg-emerald-50 text-xs font-semibold text-emerald-700 disabled:opacity-50"
              >
                ✓ Mark ทั้งหมดว่าอ่าน
              </button>
            )}
            <button
              onClick={load}
              className="px-3 py-2 rounded-lg border border-ink-200 hover:bg-ink-50 text-xs font-semibold text-ink-700"
            >
              ⟳ รีเฟรช
            </button>
          </div>
        </div>

        {/* Read/Unread tabs */}
        <div className="inline-flex rounded-lg border border-ink-200 bg-white overflow-hidden text-xs font-semibold w-fit">
          {(
            [
              { key: "unread", label: "🔔 ยังไม่อ่าน", count: unreadCount },
              { key: "read", label: "✓ อ่านแล้ว", count: readCount },
              { key: "all", label: "📨 ทั้งหมด", count: flatItems.length },
            ] as Array<{ key: ReadFilter; label: string; count: number }>
          ).map((tab) => (
            <button
              key={tab.key}
              onClick={() => setReadFilter(tab.key)}
              className={
                "px-4 py-2 transition border-r last:border-r-0 border-ink-200 " +
                (readFilter === tab.key
                  ? "bg-brand-600 text-white"
                  : "text-ink-600 hover:bg-ink-50")
              }
            >
              {tab.label}{" "}
              <span
                className={
                  "ml-1 px-1.5 py-0.5 rounded-full text-[10px] tabular-nums " +
                  (readFilter === tab.key
                    ? "bg-white/20"
                    : "bg-ink-100 text-ink-700")
                }
              >
                {tab.count}
              </span>
            </button>
          ))}
        </div>

        {error && (
          <div className="p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm">
            {error}
          </div>
        )}

        {loading && !data && (
          <div className="text-ink-400 text-sm">กำลังโหลด…</div>
        )}

        {/* Featured card — most critical / latest */}
        {featured && (
          <Link
            href={featured.link}
            className={
              "block rounded-xl border-2 p-5 hover:shadow-md transition group " +
              (featured.severity === "critical"
                ? "bg-rose-50 border-rose-300 hover:border-rose-500"
                : featured.severity === "warning"
                ? "bg-amber-50 border-amber-300 hover:border-amber-500"
                : "bg-blue-50 border-blue-200 hover:border-blue-400")
            }
          >
            <div className="flex items-start gap-4">
              <div className="text-3xl">
                {SEVERITY_ICON[featured.severity]}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1 flex-wrap">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-ink-900/70">
                    {featured.severity === "critical"
                      ? "Highest Priority"
                      : "ล่าสุด"}
                  </span>
                  <span className="text-xs text-ink-600">·</span>
                  <span className="text-xs font-semibold text-ink-700">
                    {featured.categoryIcon} {featured.categoryLabel}
                  </span>
                </div>
                <h3 className="text-base font-extrabold text-ink-900 truncate">
                  {featured.title}
                </h3>
                <p className="text-sm text-ink-700 mt-0.5 truncate">
                  {featured.subtitle}
                </p>
                <div className="text-[11px] text-ink-500 font-mono mt-2">
                  {fmtTime(featured.created_at)} · {timeAgo(featured.created_at)}
                </div>
              </div>
              <div className="text-ink-700 group-hover:text-ink-900 font-bold text-2xl transition">
                →
              </div>
            </div>
          </Link>
        )}

        {/* Category filter chips — แสดงทุก category เสมอ (count = 0 ก็เป็น grey) */}
        {data && (
          <div>
            <div className="text-[10px] font-bold text-ink-500 uppercase tracking-wider mb-2">
              ⤵ กรองตามประเภท
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <FilterChip
                label="ทั้งหมด"
                icon="📨"
                count={data.total}
                active={activeFilter === "all"}
                onClick={() => setActiveFilter("all")}
              />
              {categoryOrder.map((key) => {
                const cat = data.categories[key];
                if (!cat) return null;
                return (
                  <FilterChip
                    key={key}
                    label={cat.label}
                    icon={cat.icon}
                    count={cat.count}
                    active={activeFilter === key}
                    onClick={() => setActiveFilter(key)}
                    disabled={cat.count === 0}
                  />
                );
              })}
            </div>
          </div>
        )}

        {/* Notifications table */}
        {data && data.total === 0 ? (
          <div className="bg-white border border-ink-200 rounded-xl p-12 text-center">
            <div className="text-6xl mb-3">🎉</div>
            <div className="text-lg font-bold text-ink-900">
              ไม่มีแจ้งเตือน
            </div>
            <div className="text-sm text-ink-500 mt-1">ระบบทำงานปกติ</div>
          </div>
        ) : (
          filteredItems.length > 0 && (
            <div className="bg-white border border-ink-200 rounded-xl overflow-hidden shadow-sm">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-ink-50">
                    <tr>
                      <th className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider w-[140px]">
                        เวลา
                      </th>
                      <th className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider w-[110px]">
                        Severity
                      </th>
                      <th className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider w-[170px]">
                        ประเภท
                      </th>
                      <th className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider">
                        รายละเอียด
                      </th>
                      <th className="px-4 py-3 text-right text-[11px] font-bold text-ink-500 uppercase tracking-wider w-[110px]">
                        Action
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink-100">
                    {filteredItems.map((item) => {
                      const rowKey = `${item.categoryKey}:${item.id}`;
                      return (
                        <tr
                          key={rowKey}
                          className={
                            "hover:bg-ink-50/50 transition " +
                            (item.is_read
                              ? "opacity-60"
                              : SEVERITY_BG[item.severity] || "")
                          }
                        >
                          <td className="px-4 py-3 align-top">
                            <div className="flex items-center gap-2">
                              {!item.is_read && (
                                <span
                                  className="w-2 h-2 rounded-full bg-brand-500 animate-pulse"
                                  title="ยังไม่อ่าน"
                                />
                              )}
                              <div>
                                <div className="text-xs font-mono text-ink-700">
                                  {timeAgo(item.created_at)}
                                </div>
                                <div className="text-[10px] font-mono text-ink-400 mt-0.5">
                                  {fmtTime(item.created_at)}
                                </div>
                              </div>
                            </div>
                          </td>
                          <td className="px-4 py-3 align-top">
                            <Badge
                              tone={SEVERITY_TONE[item.severity] || "default"}
                            >
                              {SEVERITY_ICON[item.severity]}{" "}
                              {item.severity.toUpperCase()}
                            </Badge>
                          </td>
                          <td className="px-4 py-3 align-top">
                            <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-ink-100 text-ink-800 text-xs font-semibold">
                              <span>{item.categoryIcon}</span>
                              <span className="truncate max-w-[140px]">
                                {item.categoryLabel}
                              </span>
                            </div>
                          </td>
                          <td className="px-4 py-3 align-top min-w-0">
                            <div
                              className={
                                "text-sm truncate " +
                                (item.is_read
                                  ? "font-normal text-ink-700"
                                  : "font-bold text-ink-900")
                              }
                            >
                              {item.title}
                            </div>
                            <div className="text-xs text-ink-500 truncate">
                              {item.subtitle}
                            </div>
                          </td>
                          <td className="px-4 py-3 text-right align-top">
                            <div className="inline-flex items-center gap-2">
                              {item.is_read ? (
                                <button
                                  onClick={() =>
                                    markUnread(item.categoryKey, item.id)
                                  }
                                  disabled={busy === rowKey}
                                  className="px-2 py-1.5 rounded-md border border-ink-200 hover:bg-ink-50 text-ink-700 text-xs font-semibold disabled:opacity-50"
                                  title="Mark ว่ายังไม่อ่าน"
                                >
                                  ↺
                                </button>
                              ) : (
                                <button
                                  onClick={() =>
                                    markRead(item.categoryKey, item.id)
                                  }
                                  disabled={busy === rowKey}
                                  className="px-2 py-1.5 rounded-md border border-emerald-300 hover:bg-emerald-50 text-emerald-700 text-xs font-semibold disabled:opacity-50"
                                  title="Mark ว่าอ่านแล้ว"
                                >
                                  ✓
                                </button>
                              )}
                              <Link
                                href={item.link}
                                onClick={() =>
                                  !item.is_read &&
                                  markRead(item.categoryKey, item.id)
                                }
                                className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md bg-ink-900 hover:bg-ink-700 text-white text-xs font-semibold transition"
                              >
                                ดู →
                              </Link>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )
        )}

        {/* Empty state เมื่อ filter ให้ list เปล่า */}
        {data && data.total > 0 && filteredItems.length === 0 && (
          <div className="bg-white border border-ink-200 rounded-xl p-10 text-center">
            <div className="text-4xl mb-2">
              {readFilter === "unread" ? "✓" : "📭"}
            </div>
            <div className="text-sm font-bold text-ink-900">
              {readFilter === "unread"
                ? "ไม่มีรายการที่ยังไม่อ่าน"
                : "ไม่มีรายการในตัวกรองนี้"}
            </div>
          </div>
        )}
      </main>
    </>
  );
}

function FilterChip({
  label,
  icon,
  count,
  active,
  onClick,
  disabled = false,
}: {
  label: string;
  icon: string;
  count: number;
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={
        "inline-flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs font-semibold transition " +
        (active
          ? "bg-ink-900 text-white border-ink-900 shadow-sm"
          : disabled
          ? "bg-ink-50 text-ink-400 border-ink-100 cursor-not-allowed"
          : "bg-white text-ink-700 border-ink-200 hover:border-ink-400")
      }
    >
      <span>{icon}</span>
      <span>{label}</span>
      <span
        className={
          "px-1.5 py-0.5 rounded-full tabular-nums text-[10px] font-bold " +
          (active
            ? "bg-white/20 text-white"
            : disabled
            ? "bg-ink-100 text-ink-400"
            : "bg-ink-100 text-ink-700")
        }
      >
        {count}
      </span>
    </button>
  );
}
