"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { Badge } from "@/components/Badge";
import { SlidePanel } from "@/components/SlidePanel";
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
  "decided_requests",
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
  const [selected, setSelected] = useState<FlatItem | null>(null);

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
      <Topbar title="แจ้งเตือนทั้งหมด" actions={<div className="cx-command-actions">{data && <span className={`cx-chip ${unreadCount > 0 ? "warn" : "signal"}`}>{unreadCount > 0 ? `${unreadCount} UNREAD` : "ALL READ"}</span>}{unreadCount > 0 && <button className="cx-button" onClick={clearAll} disabled={busy === "clear"}>อ่านทั้งหมด</button>}<button className="cx-button" onClick={load}>รีเฟรช</button></div>} />
      <main className="cx-document signal-page space-y-5">
        <section className="cx-review-head"><span className="mono">NOTIFICATION CENTER · AUTO REFRESH 30S</span><b>สัญญาณจากระบบจริงทั้งหมด {data?.total ?? 0} รายการ</b></section>

        {/* Read/Unread tabs */}
        <div className="cx-filter-chips">
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
                "cx-chip " +
                (readFilter === tab.key
                  ? "signal"
                  : "")
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
              "cx-featured-alert " +
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

        {/* Category filter — dropdown (สะอาดกว่า chip grid) */}
        {data && (
          <CategoryDropdown
            data={data}
            activeFilter={activeFilter}
            setActiveFilter={setActiveFilter}
          />
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
            <section className="cx-panel cx-notifications"><header><div><span className="mono">EVENT STREAM</span><h2>รายการแจ้งเตือน</h2></div><span className="mono">{filteredItems.length} EVENTS</span></header>
              <div className="cx-table-wrap">
                <table>
                  <thead>
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
                              <button
                                onClick={() => {
                                  setSelected(item);
                                  if (!item.is_read)
                                    markRead(item.categoryKey, item.id);
                                }}
                                className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md bg-ink-900 hover:bg-ink-700 text-white text-xs font-semibold transition"
                              >
                                ดู →
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
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

      {/* Detail slide panel — เปิดเมื่อกด "ดู →" */}
      <SlidePanel
        open={!!selected}
        onClose={() => setSelected(null)}
        title="รายละเอียดการแจ้งเตือน"
      >
        {selected && (
          <NotificationDetailBody
            item={selected}
            onClose={() => setSelected(null)}
          />
        )}
      </SlidePanel>
    </>
  );
}

type Diagnosis = {
  symptom: string;
  causes: string[];
  fixes: string[];
  severity: "info" | "warning" | "critical";
};

function diagnose(item: FlatItem): Diagnosis | null {
  const m = (item.meta || {}) as Record<string, unknown>;
  const sub = item.subtitle || "";
  const cat = item.categoryKey;

  // ---- Subsystem Health (down/degraded incident) ----
  if (cat === "subsystem_health" && m.kind !== "health_summary") {
    const url = String(m.url || "");
    const errStr = sub.toLowerCase();
    const isLocalhost = /\b(localhost|127\.0\.0\.1)\b/.test(url);
    const latency =
      typeof m.latency_ms === "number"
        ? (m.latency_ms as number)
        : undefined;
    const isDown = item.title.includes("DOWN");
    const isDegraded = item.title.includes("DEGRADED");

    // Pattern 1: connect refused/error + localhost URL
    if (
      isLocalhost &&
      (errStr.includes("connecterror") ||
        errStr.includes("connection") ||
        errStr.includes("refused"))
    ) {
      return {
        symptom: `Hub ตามไปยัง ${url} ไม่ติด — ConnectError`,
        causes: [
          "redirect_uri ของ subsystem ตั้งเป็น `localhost` — Docker ภายใน Hub container แปล localhost = ตัว Hub เอง ไม่ใช่ subsystem",
          "ไม่มี port ใน URL → translator ของ Hub แปลงเป็น docker service-name ไม่ได้",
          "Subsystem container อาจหยุดทำงาน",
        ],
        fixes: [
          "เปลี่ยน redirect_uri เป็นมี port ระบุชัด เช่น `http://localhost:8001/oauth/callback` → Hub จะ map เป็น `http://subsystem-dorm:8000` อัตโนมัติ",
          "หรือใช้ service-name ตรงๆ ใน webhook_url (`http://subsystem-dorm:8000/...`)",
          "ตรวจ `docker compose ps` ว่า subsystem container ยัง up อยู่",
        ],
        severity: "critical",
      };
    }

    // Pattern 2: timeout
    if (errStr.includes("timeout")) {
      return {
        symptom: "Subsystem ตอบช้ากว่า 3 วินาที (timeout)",
        causes: [
          "Subsystem load สูง / DB query ช้า",
          "Network latency ระหว่าง container",
          "Subsystem block ที่ middleware (เช่น ssl handshake)",
        ],
        fixes: [
          "ดู logs ของ subsystem: `docker logs <subsystem-container> --tail 100`",
          "ตรวจ DB connection ของ subsystem",
          "ลด HEALTH_TIMEOUT_SEC ใน Hub ถ้าคิดว่า subsystem ปกติ slow",
        ],
        severity: isDown ? "critical" : "warning",
      };
    }

    // Pattern 3: HTTP 5xx
    if (errStr.match(/http 5\d\d/)) {
      return {
        symptom: `Subsystem return error response (${sub.match(/HTTP \d+/)?.[0]})`,
        causes: [
          "Subsystem มี internal exception",
          "DB connection ของ subsystem หาย",
          "/health endpoint ของ subsystem มี bug",
        ],
        fixes: [
          "ดู logs ของ subsystem container เพื่อหา stack trace",
          "เข้า DB ของ subsystem ตรวจว่า connection ปกติ",
          "ทดสอบ `curl http://localhost:<port>/health` จาก host",
        ],
        severity: isDown ? "critical" : "warning",
      };
    }

    // Pattern 4: HTTP 4xx
    if (errStr.match(/http 4\d\d/)) {
      return {
        symptom: `Subsystem return ${sub.match(/HTTP \d+/)?.[0]}`,
        causes: [
          "Endpoint `/health` ไม่มีใน subsystem",
          "Subsystem ต้องการ auth เพื่อเข้าถึง health endpoint",
        ],
        fixes: [
          "เพิ่ม endpoint `GET /health` ใน subsystem ที่ return 200",
          "ต้อง public ไม่ต้อง auth",
        ],
        severity: "warning",
      };
    }

    // Pattern 5: degraded (slow but works)
    if (isDegraded && latency != null && latency >= 1000) {
      return {
        symptom: `Subsystem ตอบที่ ${latency}ms (เกินขีด degraded 1000ms)`,
        causes: [
          "Subsystem มีโหลด CPU/Memory สูง",
          "Network ระหว่าง container ช้า",
        ],
        fixes: [
          "ดู `docker stats` ของ subsystem container",
          "ตรวจ DB query ของ /health endpoint ว่ามี join ที่ช้าไหม",
        ],
        severity: "warning",
      };
    }

    // Generic down
    if (isDown) {
      return {
        symptom: `Subsystem ${url || "ปลายทาง"} ไม่ตอบ`,
        causes: ["Container หยุดทำงาน", "Network ไม่ resolve", "URL ผิด"],
        fixes: [
          "`docker compose ps` ตรวจสถานะ container",
          "`docker compose logs <subsystem>` ดู error",
          "ตรวจ redirect_uri ที่ admin ลงทะเบียนไว้",
        ],
        severity: "critical",
      };
    }
    return null;
  }

  // ---- ML Anomaly ----
  if (cat === "ml_anomaly") {
    const decision = String(m.decision || "");
    const ip = String(m.ip || "");
    return {
      symptom: `ML ให้ risk score สูง · decision=${decision || "?"}`,
      causes: [
        "User login จาก IP ที่ไม่เคยใช้ (geo / network ต่าง)",
        "Device / User-agent ใหม่",
        "เวลาผิดปกติเทียบกับ pattern ที่ผ่านมา",
        "ความถี่ login สูงผิดปกติใน 24h",
      ],
      fixes: [
        "เข้าหน้า ML → ดู risk_breakdown ว่า feature ไหนสูง",
        `ตรวจประวัติ IP ${ip || "(N/A)"} ในตาราง login_sessions`,
        "ถ้ายืนยันว่าผิดปกติ → force-revoke session (notify/challenge/ban)",
        "ถ้าเป็น false positive → mark feedback เพื่อ retrain model",
      ],
      severity: item.severity,
    };
  }

  // ---- API Alerts (rule-based) ----
  if (cat === "api_alerts" && m.kind !== "api_summary") {
    const rule = String(m.rule || "");
    const ip = String(m.ip || "");
    const ruleMap: Record<
      string,
      { sym: string; causes: string[]; fixes: string[] }
    > = {
      excessive_requests: {
        sym: `IP ${ip} ยิง request เกินขีด`,
        causes: [
          "Bot / scraper",
          "Client code มี retry loop ที่ผิด",
          "DoS attempt",
        ],
        fixes: [
          `เพิ่ม IP ${ip} เข้า /ip-blacklist`,
          "ดู audit log ของ IP นี้ใน /audit",
          "ปรับ rate limit ใน api_guard ถ้า client ปกติ",
        ],
      },
      high_error_rate: {
        sym: `IP ${ip} มี error response เยอะ`,
        causes: [
          "Client พยายาม endpoint ที่ไม่มี (probing)",
          "JWT หมดอายุแต่ยังยิงต่อ",
          "Client misconfigured",
        ],
        fixes: [
          "ดู request_logs สำหรับ IP นี้ ว่ายิง path อะไรบ้าง",
          "ติดต่อเจ้าของ client ถ้าเป็น dev legitimate",
          "Block IP ถ้าเป็น scan",
        ],
      },
      unauthorized_probing: {
        sym: `IP ${ip} พยายามเข้า endpoint โดยไม่มีสิทธิ์`,
        causes: [
          "Attacker scan endpoint",
          "Old client code ที่ยังเก็บ endpoint เก่า",
        ],
        fixes: [
          `Block IP ${ip} ใน /ip-blacklist`,
          "เพิ่ม alert rule ถ้าเป็น path sensitive",
        ],
      },
      bot_pattern: {
        sym: `IP ${ip} มี user-agent / pattern เหมือน bot`,
        causes: [
          "Crawler / scraper",
          "Automated tool ไม่ได้ identify ตัวเอง",
        ],
        fixes: [
          "ตรวจ user-agent ในรายละเอียด",
          "Block ถ้า bot ไม่ได้ใช้งาน legitimate",
        ],
      },
    };
    const m1 = ruleMap[rule];
    if (m1) {
      return {
        symptom: m1.sym,
        causes: m1.causes,
        fixes: m1.fixes,
        severity: item.severity,
      };
    }
    return {
      symptom: `API rule "${rule}" trigger จาก IP ${ip}`,
      causes: ["มีพฤติกรรมเข้าเงื่อนไข rule"],
      fixes: [
        "ดู audit log + request_logs ของ IP นี้",
        "ตัดสินใจ block หรือ allow",
      ],
      severity: item.severity,
    };
  }

  // ---- Approval Requests (pending) ----
  if (cat === "approval_requests") {
    return {
      symptom: "Developer ส่งคำขอเปลี่ยนแปลง รออนุมัติ",
      causes: ["คำขอที่ต้อง admin review (rotate secret, edit scope, ฯลฯ)"],
      fixes: [
        "เข้าหน้า /pending-requests",
        "ตรวจสาระสำคัญและ approve หรือ reject พร้อม note",
      ],
      severity: "warning",
    };
  }

  return null;
}

function DiagnosticPanel({ item }: { item: FlatItem }) {
  const d = diagnose(item);
  if (!d) return null;

  const tone =
    d.severity === "critical"
      ? "border-rose-300 bg-rose-50"
      : d.severity === "warning"
      ? "border-amber-300 bg-amber-50"
      : "border-blue-200 bg-blue-50";

  return (
    <div className={`rounded-lg border-2 p-4 ${tone}`}>
      <div className="text-xs font-bold text-ink-900 mb-3">
        🩺 วิเคราะห์ + วิธีแก้
      </div>

      {/* Symptom */}
      <div className="mb-3">
        <div className="text-[10px] uppercase font-bold tracking-wider text-ink-500 mb-1">
          อาการ
        </div>
        <div className="text-sm text-ink-900">{d.symptom}</div>
      </div>

      {/* Causes */}
      <div className="mb-3">
        <div className="text-[10px] uppercase font-bold tracking-wider text-ink-500 mb-1">
          น่าจะมาจาก
        </div>
        <ul className="space-y-1">
          {d.causes.map((c, i) => (
            <li key={i} className="text-xs text-ink-700 flex gap-2">
              <span className="text-rose-500 shrink-0">•</span>
              <span>{c}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* Fixes */}
      <div>
        <div className="text-[10px] uppercase font-bold tracking-wider text-emerald-700 mb-1">
          วิธีแก้
        </div>
        <ol className="space-y-1">
          {d.fixes.map((f, i) => (
            <li key={i} className="text-xs text-ink-800 flex gap-2">
              <span className="text-emerald-600 shrink-0 font-bold tabular-nums">
                {i + 1}.
              </span>
              <span>{f}</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

function NotificationDetailBody({
  item,
  onClose,
}: {
  item: FlatItem;
  onClose: () => void;
}) {
  const m = (item.meta || {}) as Record<string, unknown>;
  const sevColor =
    item.severity === "critical"
      ? "border-rose-300 bg-rose-50"
      : item.severity === "warning"
      ? "border-amber-300 bg-amber-50"
      : "border-blue-200 bg-blue-50";

  // ลิงก์ navigate ที่ลงลึกขึ้นถ้ามี ID ใน meta
  let goLink = item.link;
  let goLabel = "ไปยังหน้าที่เกี่ยวข้อง";
  if (item.categoryKey === "subsystem_health" && m.subsystem_id) {
    goLink = `/subsystems/${String(m.subsystem_id)}`;
    goLabel = "เปิดหน้า Subsystem";
  } else if (
    (item.categoryKey === "approval_requests" ||
      item.categoryKey === "admin_overrides" ||
      item.categoryKey === "decided_requests") &&
    item.id
  ) {
    goLink = `/pending-requests`;
    goLabel = "เปิดหน้า Pending Requests";
  } else if (item.categoryKey === "ml_anomaly") {
    goLink = `/ml`;
    goLabel = "เปิดหน้า ML Anomaly";
  } else if (item.categoryKey === "api_alerts") {
    goLink = `/api-alerts`;
    goLabel = "เปิดหน้า API Alerts";
  }

  // ---- Specialized body per category/kind ----
  const isHealthSummary =
    item.categoryKey === "subsystem_health" && m.kind === "health_summary";
  const isApiSummary =
    item.categoryKey === "api_alerts" && m.kind === "api_summary";

  return (
    <div className="space-y-5 text-sm">
      {/* Header */}
      <div className={`rounded-lg border-2 p-4 ${sevColor}`}>
        <div className="flex items-center gap-2 mb-2">
          <Badge tone={SEVERITY_TONE[item.severity] || "default"}>
            {SEVERITY_ICON[item.severity]} {item.severity.toUpperCase()}
          </Badge>
          <span className="inline-flex items-center gap-1 text-xs font-semibold text-ink-700">
            <span>{item.categoryIcon}</span>
            <span>{item.categoryLabel}</span>
          </span>
        </div>
        <div className="text-base font-extrabold text-ink-900">
          {item.title}
        </div>
        <div className="text-xs text-ink-600 mt-1">{item.subtitle}</div>
      </div>

      {/* Quick facts */}
      <div className="space-y-1.5 border border-ink-200 rounded-lg p-3">
        <DetailRow label="เกิดเมื่อ">
          <span className="font-mono text-xs">
            {fmtTime(item.created_at)} · {timeAgo(item.created_at)}
          </span>
        </DetailRow>
        <DetailRow label="หมวด">
          <span className="text-xs">
            {item.categoryIcon} {item.categoryLabel}
          </span>
        </DetailRow>
        <DetailRow label="Severity">
          <Badge tone={SEVERITY_TONE[item.severity] || "default"}>
            {item.severity}
          </Badge>
        </DetailRow>
      </div>

      {/* Diagnostic — แสดงเฉพาะที่ "แก้ไขได้" (down/degraded/anomaly/api alert) */}
      <DiagnosticPanel item={item} />

      {/* Health summary special view */}
      {isHealthSummary && <HealthSummaryDetail meta={m} />}

      {/* API alerts summary special view */}
      {isApiSummary && <ApiSummaryDetail meta={m} />}

      {/* Generic meta highlights (other) */}
      {!isHealthSummary && !isApiSummary && Object.keys(m).length > 0 && (
        <GenericMetaHighlights meta={m} />
      )}

      {/* Raw metadata */}
      {Object.keys(m).length > 0 && (
        <details className="rounded-lg border border-ink-200 bg-ink-50 group">
          <summary className="px-3 py-2 cursor-pointer text-xs font-semibold text-ink-700 hover:text-ink-900 list-none flex items-center justify-between">
            <span>📋 Raw metadata ({Object.keys(m).length} fields)</span>
            <span className="text-ink-400 group-open:rotate-90 transition-transform">
              ▶
            </span>
          </summary>
          <pre className="px-3 py-2 border-t border-ink-200 bg-white text-[10px] font-mono text-ink-700 overflow-x-auto whitespace-pre-wrap break-all max-h-80 overflow-y-auto">
            {JSON.stringify(m, null, 2)}
          </pre>
        </details>
      )}

      {/* Footer — Actions */}
      <div className="pt-3 border-t border-ink-200 flex items-center justify-end gap-2">
        <button
          onClick={onClose}
          className="px-4 py-2 rounded-lg border border-ink-200 hover:bg-ink-50 text-ink-700 text-xs font-semibold"
        >
          ปิด
        </button>
        <Link
          href={goLink}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-ink-900 hover:bg-ink-700 text-white text-xs font-semibold transition shadow-sm hover:shadow"
          onClick={onClose}
        >
          {goLabel} →
        </Link>
      </div>

      {/* IDs */}
      <div className="text-[10px] text-ink-400 font-mono">id: {item.id}</div>
    </div>
  );
}

function DetailRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-1 border-b border-ink-100 last:border-b-0">
      <span className="text-[11px] text-ink-500 shrink-0">{label}</span>
      <span className="text-right">{children}</span>
    </div>
  );
}

function HealthSummaryDetail({ meta }: { meta: Record<string, unknown> }) {
  const counts =
    (meta.counts as Record<string, number> | undefined) || {};
  const details =
    (meta.details as Array<Record<string, unknown>> | undefined) || [];
  const total = (meta.total as number) || 0;
  const online = counts.online || 0;
  const degraded = counts.degraded || 0;
  const down = counts.down || 0;
  const unknown = counts.unknown || 0;

  return (
    <div>
      <div className="text-xs font-bold text-ink-900 mb-2">
        📊 สรุปผลตรวจสุขภาพ
      </div>

      {/* Status pills grid */}
      <div className="grid grid-cols-4 gap-2 mb-3">
        <StatusPill label="Online" count={online} tone="emerald" />
        <StatusPill label="Degraded" count={degraded} tone="amber" />
        <StatusPill label="Down" count={down} tone="rose" />
        <StatusPill label="Unknown" count={unknown} tone="ink" />
      </div>

      {/* Per-system rows (รวม Hub + subsystems) */}
      <div className="border border-ink-200 rounded-lg overflow-hidden">
        <div className="bg-ink-50 px-3 py-2 text-[10px] font-bold text-ink-500 uppercase tracking-wider grid grid-cols-12 gap-2">
          <span className="col-span-6">ระบบ</span>
          <span className="col-span-3 text-center">Status</span>
          <span className="col-span-3 text-right">Latency</span>
        </div>
        {details.length === 0 ? (
          <div className="px-3 py-4 text-center text-xs text-ink-400">
            ไม่มีข้อมูล (ระบบเช็คอาจยังไม่ทำงาน)
          </div>
        ) : (
          <div className="divide-y divide-ink-100">
            {details.map((d, i) => {
              const status = String(d.status || "unknown");
              const latency = d.latency_ms as number | undefined;
              const err = d.error as string | undefined;
              const isHub = d.kind === "hub" || d.subsystem_id === "hub";
              const components = d.components as
                | Record<string, { status: string; error?: string }>
                | undefined;
              return (
                <div key={i} className="px-3 py-2 text-xs">
                  <div className="grid grid-cols-12 gap-2 items-center">
                    <span className="col-span-6 font-semibold text-ink-900 truncate flex items-center gap-1.5">
                      <span>{isHub ? "🏛️" : "🧩"}</span>
                      <span className="truncate">{String(d.name || "—")}</span>
                      {isHub && (
                        <span className="text-[9px] font-bold uppercase tracking-wider text-brand-700 bg-brand-50 px-1 py-0.5 rounded">
                          self
                        </span>
                      )}
                    </span>
                    <span className="col-span-3 text-center">
                      <StatusBadge status={status} />
                    </span>
                    <span className="col-span-3 text-right font-mono text-ink-600">
                      {latency != null ? `${latency}ms` : "—"}
                    </span>
                  </div>

                  {/* Hub components breakdown */}
                  {isHub && components && (
                    <div className="mt-1.5 ml-6 grid grid-cols-2 gap-x-3 gap-y-1">
                      {Object.entries(components).map(([k, v]) => (
                        <div
                          key={k}
                          className="flex items-center gap-1.5 text-[10px]"
                        >
                          <span
                            className={
                              v.status === "ok"
                                ? "text-emerald-600"
                                : "text-rose-600"
                            }
                          >
                            {v.status === "ok" ? "✓" : "✗"}
                          </span>
                          <span className="font-mono text-ink-500 uppercase">
                            {k}
                          </span>
                          {v.error && (
                            <span
                              className="text-rose-500 truncate"
                              title={v.error}
                            >
                              {v.error.slice(0, 40)}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Error inline */}
                  {!isHub && err && (
                    <div
                      className="mt-1 ml-6 text-[10px] text-rose-600 truncate"
                      title={err}
                    >
                      ⚠ {err}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="text-[10px] text-ink-400 mt-2 text-right">
        {total} ระบบ (Hub + subsystems) · slot: {String(meta.slot || "—")} ·{" "}
        {String(meta.date || "")}
      </div>
    </div>
  );
}

function ApiSummaryDetail({ meta }: { meta: Record<string, unknown> }) {
  const total = (meta.total as number) || 0;
  const unresolved = (meta.unresolved as number) || 0;
  const resolved = (meta.resolved as number) || 0;
  const bySev =
    (meta.by_severity as Record<string, number> | undefined) || {};
  const topRules =
    (meta.top_rules as Array<{ rule: string; count: number }> | undefined) ||
    [];
  const topIps =
    (meta.top_ips as Array<{ ip: string; count: number }> | undefined) || [];
  const windowH = (meta.window_hours as number) || 24;

  return (
    <div>
      <div className="text-xs font-bold text-ink-900 mb-2">
        🛡️ สรุป API Alerts ({windowH}h)
      </div>

      {/* Stat pills */}
      <div className="grid grid-cols-4 gap-2 mb-3">
        <StatusPill
          label="ทั้งหมด"
          count={total}
          tone={total === 0 ? "ink" : "amber"}
        />
        <StatusPill
          label="Unresolved"
          count={unresolved}
          tone={unresolved === 0 ? "ink" : "rose"}
        />
        <StatusPill
          label="Resolved"
          count={resolved}
          tone={resolved === 0 ? "ink" : "emerald"}
        />
        <StatusPill
          label="Critical"
          count={bySev.critical || 0}
          tone={(bySev.critical || 0) === 0 ? "ink" : "rose"}
        />
      </div>

      {total === 0 ? (
        <div className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg p-3 text-center">
          ✓ ไม่พบ API alert ผิดปกติใน {windowH} ชั่วโมงที่ผ่านมา
        </div>
      ) : (
        <div className="space-y-3">
          {/* Top rules */}
          {topRules.length > 0 && (
            <div className="border border-ink-200 rounded-lg overflow-hidden">
              <div className="bg-ink-50 px-3 py-1.5 text-[10px] font-bold text-ink-500 uppercase tracking-wider">
                Top Rules
              </div>
              <div className="divide-y divide-ink-100">
                {topRules.map((r, i) => (
                  <div
                    key={i}
                    className="px-3 py-1.5 flex items-center justify-between text-xs"
                  >
                    <span className="font-mono text-ink-700">{r.rule}</span>
                    <span className="px-2 py-0.5 rounded bg-amber-100 text-amber-800 font-bold tabular-nums">
                      {r.count}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Top IPs */}
          {topIps.length > 0 && (
            <div className="border border-ink-200 rounded-lg overflow-hidden">
              <div className="bg-ink-50 px-3 py-1.5 text-[10px] font-bold text-ink-500 uppercase tracking-wider">
                Top IPs
              </div>
              <div className="divide-y divide-ink-100">
                {topIps.map((r, i) => (
                  <div
                    key={i}
                    className="px-3 py-1.5 flex items-center justify-between text-xs"
                  >
                    <span className="font-mono text-ink-700">{r.ip}</span>
                    <span className="px-2 py-0.5 rounded bg-ink-100 text-ink-700 font-bold tabular-nums">
                      {r.count}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <div className="text-[10px] text-ink-400 mt-2 text-right">
        slot: {String(meta.slot || "—")} · {String(meta.date || "")}
      </div>
    </div>
  );
}

function StatusPill({
  label,
  count,
  tone,
}: {
  label: string;
  count: number;
  tone: "emerald" | "amber" | "rose" | "ink";
}) {
  const styles: Record<string, string> = {
    emerald: "bg-emerald-50 border-emerald-200 text-emerald-800",
    amber: "bg-amber-50 border-amber-200 text-amber-800",
    rose: "bg-rose-50 border-rose-200 text-rose-800",
    ink: "bg-ink-50 border-ink-200 text-ink-700",
  };
  return (
    <div
      className={`rounded-lg border p-2 text-center ${styles[tone]} ${
        count === 0 ? "opacity-50" : ""
      }`}
    >
      <div className="text-lg font-extrabold tabular-nums">{count}</div>
      <div className="text-[10px] uppercase tracking-wider font-semibold">
        {label}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { bg: string; text: string; icon: string }> = {
    online: { bg: "bg-emerald-100", text: "text-emerald-800", icon: "🟢" },
    degraded: { bg: "bg-amber-100", text: "text-amber-800", icon: "🟡" },
    down: { bg: "bg-rose-100", text: "text-rose-800", icon: "🔴" },
    unknown: { bg: "bg-ink-100", text: "text-ink-700", icon: "⚪" },
  };
  const s = map[status] || map.unknown;
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold ${s.bg} ${s.text}`}
    >
      {s.icon} {status}
    </span>
  );
}

function GenericMetaHighlights({ meta }: { meta: Record<string, unknown> }) {
  // หยิบเฉพาะ key ที่น่าสนใจขึ้นมาแสดง (ที่เหลือดูใน raw)
  const highlights: Array<[string, string]> = [];
  const push = (label: string, key: string) => {
    const v = meta[key];
    if (v != null && v !== "") highlights.push([label, String(v)]);
  };
  push("Request type", "request_type");
  push("Status", "status");
  push("Reviewer note", "reviewer_note");
  push("Rule", "rule");
  push("IP", "ip");
  push("Session ID", "session_id");
  push("Decision", "decision");
  push("URL", "url");

  if (highlights.length === 0) return null;

  return (
    <div>
      <div className="text-xs font-bold text-ink-900 mb-2">ข้อมูลสำคัญ</div>
      <div className="border border-ink-200 rounded-lg p-3 space-y-1">
        {highlights.map(([label, value]) => (
          <DetailRow key={label} label={label}>
            <span className="text-xs font-mono text-ink-800 break-all">
              {value}
            </span>
          </DetailRow>
        ))}
      </div>
    </div>
  );
}

function CategoryDropdown({
  data,
  activeFilter,
  setActiveFilter,
}: {
  data: NotificationsResponse;
  activeFilter: string;
  setActiveFilter: (s: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // ปิดเมื่อคลิกข้างนอก
  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const current =
    activeFilter === "all"
      ? { label: "ทั้งหมด", icon: "📨", count: data.total }
      : data.categories[activeFilter]
      ? {
          label: data.categories[activeFilter].label,
          icon: data.categories[activeFilter].icon,
          count: data.categories[activeFilter].count,
        }
      : { label: "ทั้งหมด", icon: "📨", count: data.total };

  function select(key: string) {
    setActiveFilter(key);
    setOpen(false);
  }

  return (
    <div className="relative w-full max-w-md" ref={ref}>
      <div className="text-[10px] font-bold text-ink-500 uppercase tracking-wider mb-2">
        ⤵ กรองตามประเภท
      </div>

      {/* Trigger */}
      <button
        onClick={() => setOpen((v) => !v)}
        className={
          "w-full flex items-center justify-between gap-3 px-4 py-2.5 rounded-xl border bg-white text-left transition shadow-sm " +
          (open
            ? "border-ink-900 ring-2 ring-ink-900/10"
            : "border-ink-200 hover:border-ink-400")
        }
      >
        <span className="flex items-center gap-2 min-w-0">
          <span className="text-lg shrink-0">{current.icon}</span>
          <span className="text-sm font-semibold text-ink-900 truncate">
            {current.label}
          </span>
          <span className="px-2 py-0.5 rounded-full bg-ink-100 text-ink-700 text-[10px] font-bold tabular-nums shrink-0">
            {current.count}
          </span>
        </span>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          className={`w-4 h-4 text-ink-500 transition ${open ? "rotate-180" : ""}`}
        >
          <path
            fillRule="evenodd"
            d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"
            clipRule="evenodd"
          />
        </svg>
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute left-0 right-0 mt-1.5 z-30 bg-white border border-ink-200 rounded-xl shadow-xl overflow-hidden">
          <DropdownItem
            icon="📨"
            label="ทั้งหมด"
            count={data.total}
            selected={activeFilter === "all"}
            onClick={() => select("all")}
          />
          <div className="border-t border-ink-100" />
          {categoryOrder.map((key) => {
            const cat = data.categories[key];
            if (!cat) return null;
            return (
              <DropdownItem
                key={key}
                icon={cat.icon}
                label={cat.label}
                count={cat.count}
                selected={activeFilter === key}
                onClick={() => select(key)}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

function DropdownItem({
  icon,
  label,
  count,
  selected,
  onClick,
}: {
  icon: string;
  label: string;
  count: number;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={
        "w-full flex items-center justify-between gap-3 px-4 py-2.5 text-left transition " +
        (selected
          ? "bg-ink-900 text-white"
          : count === 0
          ? "text-ink-400 hover:bg-ink-50"
          : "text-ink-700 hover:bg-ink-50")
      }
    >
      <span className="flex items-center gap-2 min-w-0">
        <span className="text-base shrink-0">{icon}</span>
        <span className="text-sm font-medium truncate">{label}</span>
      </span>
      <span className="flex items-center gap-2 shrink-0">
        <span
          className={
            "px-2 py-0.5 rounded-full tabular-nums text-[10px] font-bold " +
            (selected
              ? "bg-white/20 text-white"
              : count === 0
              ? "bg-ink-100 text-ink-400"
              : "bg-ink-100 text-ink-700")
          }
        >
          {count}
        </span>
        {selected && <span className="text-xs">✓</span>}
      </span>
    </button>
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
