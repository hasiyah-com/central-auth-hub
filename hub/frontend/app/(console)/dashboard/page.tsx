"use client";

/**
 * SOC Dashboard — Signal Room layout (พื้นสว่าง + การ์ดขาว + accent teal)
 *
 * โครงหน้าตามดีไซน์อ้างอิง: header → action required → KPI 5 →
 * authentication traffic + service health matrix → recent access + risk engine →
 * risk distribution + security signals → auth policy
 *
 * ข้อมูลจริงทั้งหมด ไม่มีค่าสมมติ:
 *   /admin/overview · /admin/dashboard/map
 *   /admin/notifications/count · /admin/dashboard/insights · /admin/activity
 *   /admin/subsystems/{id}/health-history  (sparkline + uptime)
 *
 * หมายเหตุความซื่อตรงของข้อมูล:
 *  - ต้นแบบเขียน "UPTIME · 30D" แต่ health history เก็บ 288 จุด × 5 นาที = 24 ชม.
 *    จึงเขียนป้ายเป็น "UPTIME · 24H" ตามช่วงที่มีข้อมูลจริง
 *  - ค่าที่ไม่มี baseline → บอกตรงๆ ว่าไม่มีข้อมูลเทียบ ไม่แสดง 0%
 *  - B51: เช็ค "ยังไม่โหลด" จาก source object ไม่ใช่ค่าที่คำนวณได้ (0 จริงต้องเป็น 0)
 */

import { useEffect, useState } from "react";
import Link from "next/link";
// design system ที่ port มาจากดีไซน์ตัวจริง (central-auth-hub-signal) — ทุกกฎ scope ใต้ .sr
import "../../signal-room.css";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";
import { LoginMethodsCard } from "./_components/LoginMethodsCard";

type Overview = {
  users: { total: number; active: number };
  subsystems: { total: number; active: number; pending: number };
  logins: { total: number; blocked: number };
};


type NotifCategoryCounts = {
  approval_requests: number;
  ml_anomaly: number;
  api_alerts: number;
  subsystem_health: number;
};

type NotifCount = {
  total: number;
  unread?: number;
  /** ทั้งหมดตลอดกาล (อ่านแล้ว+ยังไม่อ่าน) */
  by_category: NotifCategoryCounts;
  /** เฉพาะที่ยังไม่อ่าน — ต้องคู่กับ `unread` เสมอ ไม่งั้นหัวข้อกับรายละเอียดเป็นคนละชุดเลข */
  unread_by_category?: NotifCategoryCounts;
};

type SubsystemLite = {
  id: string;
  name: string;
  status: string;
  health: string | null;
  latency_ms: number | null;
};

type MapData = {
  geo: { country: string; risk: "green" | "yellow" | "red"; count: number }[];
  decisions: Record<string, number>;
  subsystems: SubsystemLite[];
  active_now: number;
};

type Insights = {
  window_hours: number;
  users: { total: number; new_30d: number };
  logins: { today: number; yesterday: number; change_pct: number | null };
  risk: {
    avg_today: number | null;
    avg_yesterday: number | null;
    delta: number | null;
    thresholds: { warn: number; challenge: number; block: number };
    distribution: {
      low: number;
      medium: number;
      high: number;
      critical: number;
      scored_total: number;
    };
  };
  signals: { key: string; label: string; count: number }[];
  attack_ip: { sessions: number; pct: number | null };
};

type HourBucket = {
  hour: string | null;
  count: number;
  blocked: number;
  challenged: number;
};

type ActivityItem = {
  id: string;
  created_at: string | null;
  user_email: string | null;
  full_name: string | null;
  subsystem_name: string | null;
  risk_score: number | null;
  decision: string | null;
  ip: string | null;
  is_attack_ip: boolean;
};

type ActivityResp = {
  items: ActivityItem[];
  kpis: {
    total: number;
    blocked: number;
    challenged: number;
    unique_users: number;
    avg_risk: number | null;
    online: number;
  };
  hourly: HourBucket[];
};

type HealthPoint = { status?: string | null; latency_ms?: number | null };
type HealthHistory = Record<string, HealthPoint[]>;

const CATEGORY_LABELS: Record<string, { label: string; icon: string }> = {
  approval_requests: { label: "คำขอ Approve", icon: "📋" },
  ml_anomaly: { label: "ML Anomaly", icon: "🧠" },
  api_alerts: { label: "API Alerts", icon: "🛡️" },
  subsystem_health: { label: "Subsystem ล่ม", icon: "🟢" },
};

type HealthCheckResult = { ok: boolean; subsystems?: number };

const OK_STATUS = new Set(["online", "healthy", "ok"]);

/** จัดกลุ่ม decision → 3 ระดับ */
function decisionGroups(d: Record<string, number>) {
  const g = { allow: 0, watch: 0, block: 0 };
  for (const [k, v] of Object.entries(d)) {
    if (k === "allow" || k === "mfa_passed") g.allow += v;
    else if (k.includes("block")) g.block += v;
    else g.watch += v;
  }
  return g;
}

/** timestamp จาก backend เป็น UTC (naive) — ต้องเติม Z ก่อนแปลงเป็นเวลาไทย */
function toDate(iso: string) {
  return new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
}

function timeTH(iso: string | null) {
  if (!iso) return "—";
  return toDate(iso).toLocaleTimeString("th-TH", {
    timeZone: "Asia/Bangkok",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

/**
 * เติมช่องชั่วโมงให้ครบ 24 ช่องเสมอ (ชั่วโมงที่ไม่มี login = 0)
 * ถ้าไม่เติม กราฟจะเหลือแท่งเดียวกินความกว้างทั้งหมดเมื่อข้อมูลน้อย
 */
function build24h(hourly: HourBucket[]) {
  const byHour = new Map<number, HourBucket>();
  for (const b of hourly) {
    if (!b.hour) continue;
    byHour.set(toDate(b.hour).getTime(), b);
  }
  const now = new Date();
  const slots: { key: number; label: string; b: HourBucket | null }[] = [];
  for (let i = 23; i >= 0; i--) {
    const d = new Date(now.getTime() - i * 3600_000);
    d.setMinutes(0, 0, 0);
    const t = d.getTime();
    slots.push({
      key: t,
      label: d.toLocaleTimeString("th-TH", {
        timeZone: "Asia/Bangkok",
        hour: "2-digit",
        hour12: false,
      }),
      b: byHour.get(t) ?? null,
    });
  }
  return slots;
}

/** เส้น sparkline จาก latency history */
function sparkPath(points: HealthPoint[], w = 64, h = 20) {
  const vals = points
    .map((p) => p.latency_ms)
    .filter((v): v is number => typeof v === "number");
  if (vals.length < 2) return null;
  const recent = vals.slice(-24);
  const min = Math.min(...recent);
  const max = Math.max(...recent);
  const span = max - min || 1;
  return recent
    .map((v, i) => {
      const x = (i / (recent.length - 1)) * w;
      const y = h - ((v - min) / span) * h;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

function uptimePct(points: HealthPoint[]) {
  if (!points.length) return null;
  const ok = points.filter((p) => OK_STATUS.has((p.status || "").toLowerCase())).length;
  return Math.round((ok / points.length) * 10000) / 100;
}

/** ไอคอนเส้น 18px — ใช้สีข้อความปัจจุบัน */
function Svg({ children, size = 18 }: { children: React.ReactNode; size?: number }) {
  return (
    <svg
      viewBox="0 0 18 18"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

const IconUsers = () => (
  <Svg size={16}>
    <circle cx="6.5" cy="6" r="2.6" />
    <path d="M2 15c0-2.5 2-4.2 4.5-4.2S11 12.5 11 15" />
    <path d="M11.5 10.9c2 .3 3.5 1.9 3.5 4.1" />
    <circle cx="12.4" cy="6.4" r="2.1" />
  </Svg>
);
const IconNetwork = () => (
  <Svg size={16}>
    <rect x="6.5" y="1.5" width="5" height="4" rx="1" />
    <rect x="1.5" y="12.5" width="4.5" height="4" rx="1" />
    <rect x="12" y="12.5" width="4.5" height="4" rx="1" />
    <path d="M9 5.5v3.5M3.75 12.5V9H14.25v3.5" />
  </Svg>
);
const IconKey = () => (
  <Svg size={16}>
    <circle cx="5.5" cy="9" r="3.2" />
    <path d="M8.7 9H16M13.5 9v2.6M11 9v2" />
  </Svg>
);
const IconAlert = () => (
  <Svg size={16}>
    <path d="M9 2.5 16.5 15H1.5z" />
    <path d="M9 7v3.5M9 12.8v.2" />
  </Svg>
);
const IconGauge = () => (
  <Svg size={16}>
    <path d="M2.6 13a7 7 0 1 1 12.8 0" />
    <path d="M9 13 12 7.5" />
  </Svg>
);
const IconShield = () => (
  <Svg size={15}>
    <path d="M9 1.8 15 4v5c0 3.6-2.5 6.3-6 7.2C5.5 15.3 3 12.6 3 9V4z" />
    <path d="M6.4 8.9 8.3 10.8 11.8 7.3" />
  </Svg>
);
const IconRefresh = () => (
  <Svg size={15}>
    <path d="M15.2 7.6A6.4 6.4 0 0 0 3.9 5.2M2.8 10.4a6.4 6.4 0 0 0 11.3 2.4" />
    <path d="M15.5 2.8v4.8h-4.8M2.5 15.2v-4.8h4.8" />
  </Svg>
);
const IconBolt = () => (
  <Svg size={18}>
    <path d="M10 1.8 4 10h4l-1 6.2L14 8h-4z" />
  </Svg>
);

export default function DashboardPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [notif, setNotif] = useState<NotifCount | null>(null);
  const [map, setMap] = useState<MapData | null>(null);
  const [ins, setIns] = useState<Insights | null>(null);
  const [act, setAct] = useState<ActivityResp | null>(null);
  const [hist, setHist] = useState<HealthHistory>({});
  const [error, setError] = useState<string | null>(null);
  const [hcBusy, setHcBusy] = useState(false);
  const [hcResult, setHcResult] = useState<HealthCheckResult | null>(null);
  const [hcError, setHcError] = useState<string | null>(null);

  const refreshLive = () => {
    clientFetch<NotifCount>("/admin/notifications/count").then(setNotif).catch(() => {});
    clientFetch<MapData>("/admin/dashboard/map").then(setMap).catch(() => {});
    clientFetch<Insights>("/admin/dashboard/insights?hours=24").then(setIns).catch(() => {});
    clientFetch<ActivityResp>("/admin/activity?hours=24&limit=5").then(setAct).catch(() => {});
  };

  const runHealthCheckNow = async () => {
    setHcBusy(true);
    setHcError(null);
    setHcResult(null);
    try {
      const res = await clientFetch<HealthCheckResult>(
        "/admin/subsystems/health/emit-summary-now",
        { method: "POST" }
      );
      setHcResult(res);
      refreshLive();
    } catch (e) {
      const err = e as { detail?: string };
      setHcError(err.detail || "ตรวจสอบไม่สำเร็จ");
    } finally {
      setHcBusy(false);
    }
  };

  useEffect(() => {
    Promise.all([
      clientFetch<Overview>("/admin/overview"),
      clientFetch<NotifCount>("/admin/notifications/count").catch(() => null),
      clientFetch<MapData>("/admin/dashboard/map").catch(() => null),
      clientFetch<Insights>("/admin/dashboard/insights?hours=24").catch(() => null),
      clientFetch<ActivityResp>("/admin/activity?hours=24&limit=5").catch(() => null),
    ])
      .then(([ov, nc, mp, iv, ac]) => {
        setData(ov);
        if (nc) setNotif(nc);
        if (mp) setMap(mp);
        if (iv) setIns(iv);
        if (ac) setAct(ac);
      })
      .catch((e) => setError(e.detail || "โหลดข้อมูลไม่สำเร็จ"));

    const t = setInterval(refreshLive, 30_000);
    return () => clearInterval(t);
  }, []);

  // sparkline + uptime ต่อ subsystem — ยิงหลังรู้รายชื่อระบบย่อยแล้ว
  useEffect(() => {
    const actives = map?.subsystems.filter((s) => s.status === "active") ?? [];
    if (!actives.length) return;
    let stopped = false;
    Promise.all(
      actives.map((s) =>
        clientFetch<{ points?: HealthPoint[] } | HealthPoint[]>(
          `/admin/subsystems/${s.id}/health-history?limit=288`
        )
          .then((r) => [s.id, Array.isArray(r) ? r : (r.points ?? [])] as const)
          .catch(() => [s.id, [] as HealthPoint[]] as const)
      )
    ).then((pairs) => {
      if (!stopped) setHist(Object.fromEntries(pairs));
    });
    return () => {
      stopped = true;
    };
  }, [map?.subsystems.length]);

  const dec = map ? decisionGroups(map.decisions) : null;
  const decTotal = dec ? dec.allow + dec.watch + dec.block : 0;
  const activeSubs = map?.subsystems.filter((s) => s.status === "active") ?? [];
  const healthySubs = activeSubs.filter((s) => OK_STATUS.has((s.health || "").toLowerCase()));

  const k = act?.kpis;
  const successPct =
    k && k.total > 0 ? Math.round(((k.total - k.blocked) / k.total) * 1000) / 10 : null;
  const highRisk = k ? k.blocked + k.challenged : null;
  const slots = act ? build24h(act.hourly) : null;
  const maxBar = slots ? Math.max(...slots.map((s) => s.b?.count ?? 0), 1) : 1;
  const peak = slots
    ? slots.reduce((a, b) => ((b.b?.count ?? 0) > (a.b?.count ?? 0) ? b : a))
    : null;
  const blockedPeak = slots
    ? slots.reduce((a, b) => ((b.b?.blocked ?? 0) > (a.b?.blocked ?? 0) ? b : a))
    : null;
  const dist = ins?.risk.distribution;
  const latencies = activeSubs
    .map((s) => s.latency_ms)
    .filter((v): v is number => typeof v === "number")
    .sort((a, b) => a - b);
  const medianLatency = latencies.length
    ? latencies[Math.floor(latencies.length / 2)]
    : null;

  const label = "font-mono text-[10px] uppercase tracking-[.16em] text-ink-400";
  // ใช้คลาส .card ของดีไซน์ (มุมเหลี่ยม + hairline 1px + ไม่มีเงา) แทน rounded-xl เดิม
  // — ตัวแปรนี้ถูกใช้กับการ์ดทุกใบในหน้า เปลี่ยนที่เดียวเปลี่ยนทั้งหน้า
  const card = "card";

  return (
    <>
      <Topbar title="ภาพรวมระบบ" />
      {/* command-bar กินเต็มความกว้าง (ไม่มี padding ครอบ) ส่วนเนื้อหาอยู่ใน .document
          ที่คุมระยะห่างเอง — ช่องไฟระหว่างบล็อก 10px ตามดีไซน์ ไม่ใช่ 20px แบบเดิม */}
      <main className="sr">
        <div className="dashboard-stack">
          {error && (
            <div className="border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
              {error}
            </div>
          )}

          {/* ── command bar (แถบหัวพื้นเข้มตามดีไซน์) ── */}
          <section className="command-bar">
            <div className="command-copy">
              <div className="live-label">
                <span className="signal-dot">
                  <i />
                </span>
                live control surface
              </div>
              <h1>ภาพรวมระบบ</h1>
            </div>

            <div className="command-actions">
              <div className="health-stamp">
                <IconShield />
                <div>
                  <span>system status</span>
                  <strong>
                    {!map
                      ? "กำลังตรวจสอบ"
                      : activeSubs.length === 0
                        ? "ยังไม่มีระบบย่อย"
                        : healthySubs.length === activeSubs.length
                          ? "ทุกระบบทำงานปกติ"
                          : `${activeSubs.length - healthySubs.length} ระบบผิดปกติ`}
                  </strong>
                </div>
              </div>
              <button onClick={runHealthCheckNow} disabled={hcBusy} className="refresh">
                {hcBusy ? (
                  "กำลังตรวจ…"
                ) : (
                  <>
                    <IconRefresh />
                    ตรวจสุขภาพ
                  </>
                )}
              </button>
            </div>
          </section>

          {hcResult && hcResult.ok && (
            <div className="flex items-center gap-2 border border-brand-500/40 bg-brand-50 px-3 py-2 text-xs text-brand-700">
              ✓ ตรวจเสร็จ — Hub + {hcResult.subsystems} subsystem
              <Link href="/notifications" className="ml-1 font-bold underline hover:no-underline">
                รายงาน →
              </Link>
            </div>
          )}
          {hcError && (
            <div className="border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
              ✗ {hcError}
            </div>
          )}

          {/* ── action required ── */}
          {notif && (notif.unread ?? 0) > 0 && (
            <Link href="/notifications" className="attention-banner">
              <span className="banner-icon">
                <IconBolt />
              </span>
              <div className="min-w-0 flex-1">
                <span className="overline">action required</span>
                <strong>มี {notif.unread} รายการที่รอการตรวจสอบ</strong>
                <p className="truncate">
                    {/* ต้องเป็น unread_by_category ให้ตรงกับหัวข้อที่ใช้ notif.unread —
                        ถ้าใช้ by_category (ยอดตลอดกาล) ผลรวมจะไม่ตรงกับเลขหัวข้อ
                        (เคยเห็นจริง: หัวบอก 30 แต่ breakdown บวกได้ 49) */}
                    {Object.entries(notif.unread_by_category ?? notif.by_category)
                      .filter(([, c]) => c > 0)
                      .map(([key, c]) => `${CATEGORY_LABELS[key]?.label ?? key} ${c}`)
                      .join(" · ") || "—"}
                </p>
              </div>
              <span className="link-button">
                เปิดรายการงาน <span>→</span>
              </span>
            </Link>
          )}

          {/* ── KPI ── โครง + สเกลตามดีไซน์ (.kpi-grid/.kpi ใน signal-room.css) */}
          <section className="kpi-grid">
            {[
              {
                tone: "signal-kpi",
                label: "users total",
                value: data ? data.users.total : "—",
                icon: <IconUsers />,
                sub: ins ? (
                  <>
                    <span className="font-semibold text-brand-600">+{ins.users.new_30d}</span> ใน 30
                    วันที่ผ่านมา
                  </>
                ) : (
                  "—"
                ),
              },
              {
                label: "subsystems",
                value: data ? data.subsystems.active : "—",
                icon: <IconNetwork />,
                sub: data ? (
                  <>
                    <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-brand-500 align-middle" />
                    {data.subsystems.active} active · {data.subsystems.pending} pending
                  </>
                ) : (
                  "—"
                ),
              },
              {
                label: "logins · 24h",
                value: k ? k.total : "—",
                icon: <IconKey />,
                sub:
                  successPct !== null ? (
                    <>
                      <span className="font-semibold text-ink-700">{successPct}%</span> สำเร็จ
                    </>
                  ) : (
                    "ยังไม่มีข้อมูล"
                  ),
              },
              {
                tone: "risk-kpi",
                label: "high risk",
                value: highRisk !== null ? highRisk : "—",
                icon: <IconAlert />,
                sub: k ? (
                  <>
                    <span className={k.blocked > 0 ? "font-semibold text-rose-600" : ""}>
                      {k.blocked} blocked
                    </span>{" "}
                    · {k.challenged} challenged
                  </>
                ) : (
                  "—"
                ),
              },
              {
                label: "avg. risk",
                value: ins && ins.risk.avg_today !== null ? ins.risk.avg_today.toFixed(2) : "—",
                icon: <IconGauge />,
                sub:
                  ins && ins.risk.delta !== null ? (
                    <>
                      {ins.risk.delta >= 0 ? "สูงกว่า" : "ต่ำกว่า"}เมื่อวาน{" "}
                      <span
                        className={`font-semibold ${
                          ins.risk.delta >= 0 ? "text-amber-600" : "text-brand-600"
                        }`}
                      >
                        {Math.abs(ins.risk.delta).toFixed(2)}
                      </span>
                    </>
                  ) : (
                    "ไม่มีข้อมูลเทียบ"
                  ),
              },
            ].map((c) => (
              <article key={c.label} className={`kpi ${c.tone ?? ""}`}>
                <div className="kpi-head">
                  <span>{c.label}</span>
                  {c.icon}
                </div>
                <strong className="mono">{c.value}</strong>
                <p>{c.sub}</p>
              </article>
            ))}
          </section>

          {/* ── traffic + service health ── grid ตามดีไซน์ (.security-overview-grid) */}
          <div className="security-overview-grid">
            {/* authentication traffic */}
            <section className="card">
              <div className="card-head chart-card-head">
                <div>
                  <span className="overline">authentication traffic</span>
                  <h2>ปริมาณการยืนยันตัวตน · 24 ชั่วโมง</h2>
                </div>
                <div className="chart-legend">
                  <span>
                    <i className="allow" /> Allow
                  </span>
                  <span>
                    <i className="mfa" /> Challenge
                  </span>
                  <span>
                    <i className="block" /> Block
                  </span>
                </div>
              </div>

              {!slots ? (
                <div className="grid h-56 place-items-center text-sm text-ink-400">
                  กำลังโหลด…
                </div>
              ) : (
                <>
                  <div className="px-5">
                    <div className="flex gap-3">
                      {/* y axis */}
                      <div className="flex w-8 shrink-0 flex-col justify-between py-0.5 text-right font-mono text-[9px] text-ink-400">
                        {[maxBar, Math.round(maxBar * 0.75), Math.round(maxBar * 0.5), Math.round(maxBar * 0.25), 0].map(
                          (v, i) => (
                            <div key={i}>{v}</div>
                          )
                        )}
                      </div>
                      {/* plot */}
                      <div className="relative h-44 flex-1">
                        {[0, 25, 50, 75, 100].map((p) => (
                          <div
                            key={p}
                            className="absolute inset-x-0 border-t border-ink-100"
                            style={{ top: `${p}%` }}
                          />
                        ))}
                        <div className="absolute inset-0 flex items-end gap-[3px]">
                          {slots.map((s) => {
                            const b = s.b;
                            const total = b?.count ?? 0;
                            const blocked = b?.blocked ?? 0;
                            const challenged = b?.challenged ?? 0;
                            const allow = Math.max(total - blocked - challenged, 0);
                            const pct = (n: number) => `${(n / maxBar) * 100}%`;
                            return (
                              <div
                                key={s.key}
                                className="flex h-full flex-1 flex-col justify-end"
                                title={`${s.label}:00 — ${total} ครั้ง (challenge ${challenged} · block ${blocked})`}
                              >
                                {total > 0 ? (
                                  <>
                                    <div
                                      style={{ height: pct(blocked) }}
                                      className="bg-rose-500"
                                    />
                                    <div style={{ height: pct(challenged) }} className="bg-amber-400" />
                                    <div style={{ height: pct(allow) }} className="bg-brand-500" />
                                  </>
                                ) : (
                                  <div className="h-[2px] bg-ink-100" />
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                    {/* x axis */}
                    <div className="ml-11 mt-1.5 flex gap-[3px] font-mono text-[9px] text-ink-400">
                      {slots.map((s, i) => (
                        <div key={s.key} className="flex-1 text-center">
                          {i % 3 === 0 ? s.label : ""}
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="chart-summary">
                    <div>
                      <span>ช่วงสูงสุด</span>
                      <b className="mono">
                        {peak && (peak.b?.count ?? 0) > 0
                          ? `${peak.label}:00 · ${peak.b?.count}`
                          : "ยังไม่มี"}
                      </b>
                    </div>
                    <div>
                      <span>เทียบเมื่อวาน</span>
                      <b
                        className={`mono ${
                          ins?.logins.change_pct == null
                            ? ""
                            : ins.logins.change_pct >= 0
                              ? "positive"
                              : "danger-text"
                        }`}
                      >
                        {ins?.logins.change_pct == null
                          ? "ไม่มีข้อมูลเทียบ"
                          : `${ins.logins.change_pct >= 0 ? "+" : ""}${ins.logins.change_pct}%`}
                      </b>
                    </div>
                    <div>
                      <span>blocked peak</span>
                      <b
                        className={`mono ${
                          (blockedPeak?.b?.blocked ?? 0) > 0 ? "danger-text" : ""
                        }`}
                      >
                        {blockedPeak && (blockedPeak.b?.blocked ?? 0) > 0
                          ? `${blockedPeak.b?.blocked} events · ${blockedPeak.label}:00`
                          : "0 events"}
                      </b>
                    </div>
                  </div>
                </>
              )}
            </section>

            {/* service health matrix */}
            <section className="subsystem-card">
              <div className="subsystem-head">
                <div>
                  <span className="overline">service health matrix</span>
                  <h2>การเชื่อมต่อระบบย่อย</h2>
                </div>
                <div className="matrix-health">
                  <span className="signal-dot">
                    <i />
                  </span>
                  <span>
                    <b className="mono">
                      {map ? `${healthySubs.length} / ${activeSubs.length}` : "—"}
                    </b>
                    healthy
                  </span>
                </div>
              </div>

              {!map ? (
                <div className="px-5 pb-6 text-sm text-ink-400">กำลังโหลด…</div>
              ) : activeSubs.length === 0 ? (
                <div className="px-5 pb-6 text-sm text-ink-400">ยังไม่มีระบบย่อย</div>
              ) : (
                <>
                  <div className="matrix-labels mono">
                    <span>SERVICE</span>
                    <span>UPTIME · 24H</span>
                    <span>LATENCY</span>
                  </div>
                  <div className="service-matrix">
                    {activeSubs.map((s, i) => {
                      const pts = hist[s.id] ?? [];
                      const up = uptimePct(pts);
                      const path = sparkPath(pts);
                      const ok = OK_STATUS.has((s.health || "").toLowerCase());
                      const slow = (s.latency_ms ?? 0) >= 500;
                      return (
                        <Link
                          key={s.id}
                          href={`/subsystems/${s.id}`}
                          className="service-row"
                        >
                          <div className="service-index mono">
                            <span>{String(i + 1).padStart(2, "0")}</span>
                            <i />
                          </div>
                          <div className="service-name">
                            <strong className="truncate">{s.name}</strong>
                            <span className="mono truncate">{s.health || "unknown"}</span>
                          </div>
                          <div className="uptime-value">
                            <b className="mono">{up !== null ? `${up}%` : "—"}</b>
                            <span>
                              {up !== null ? `${pts.length} จุด` : "ไม่มีประวัติ"}
                            </span>
                          </div>
                          <div className="latency-value">
                            <b className="mono">
                              {s.latency_ms != null ? (
                                <>
                                  {s.latency_ms} <small>ms</small>
                                </>
                              ) : (
                                "—"
                              )}
                            </b>
                            <span
                              className={`latency-state ${
                                ok && !slow ? "fast" : "watch"
                              }`}
                            >
                              {slow ? "watch" : ok ? "normal" : s.health || "unknown"}
                            </span>
                          </div>
                          {path ? (
                            <svg
                              className={`latency-spark ${slow ? "watch" : "fast"}`}
                              viewBox="0 0 64 20"
                              preserveAspectRatio="none"
                              aria-label={`แนวโน้ม latency ${s.name}`}
                            >
                              <path d={path} />
                            </svg>
                          ) : (
                            <span />
                          )}
                        </Link>
                      );
                    })}
                  </div>
                  <div className="subsystem-foot">
                    <span>
                      ตรวจทุก <b>5 นาที</b>
                    </span>
                    {medianLatency !== null && (
                      <span>
                        Median <b>{medianLatency}ms</b>
                      </span>
                    )}
                  </div>
                </>
              )}
            </section>
          </div>

          {/* ── recent access + risk engine ── */}
          <div className="main-grid">
            <section className="card activity-card overflow-hidden">
              <div className="card-head">
                <div>
                  <span className="overline">recent access</span>
                  <h2>การเข้าใช้งานล่าสุด</h2>
                </div>
                <Link href="/activity" className="link-button">
                  ดู Realtime ทั้งหมด <span>→</span>
                </Link>
              </div>
              {!act ? (
                <div className="py-8 text-center text-sm text-ink-400">กำลังโหลด…</div>
              ) : act.items.length === 0 ? (
                <div className="py-8 text-center text-sm text-ink-400">
                  ยังไม่มีการเข้าใช้งานใน 24 ชั่วโมงที่ผ่านมา
                </div>
              ) : (
                <>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>เวลา</th>
                          <th>ผู้ใช้งาน</th>
                          <th>ระบบ</th>
                          <th>IP ADDRESS</th>
                          <th>RISK SCORE</th>
                          <th>DECISION</th>
                        </tr>
                      </thead>
                      <tbody>
                        {act.items.map((it) => {
                          const d = (it.decision || "").replace("would_", "");
                          // ระดับสีเดียวกันทั้ง meter และป้าย: allow=low · block=crit · อื่น=mid
                          const tone =
                            d === "allow" || d === "mfa_passed"
                              ? "low"
                              : d === "block"
                                ? "crit"
                                : "mid";
                          const pct = Math.round((it.risk_score ?? 0) * 100);
                          return (
                            <tr key={it.id}>
                              <td className="mono time-cell">{timeTH(it.created_at)}</td>
                              <td className="mono email-cell">
                                {it.user_email || it.full_name || "—"}
                              </td>
                              <td>{it.subsystem_name || "Hub"}</td>
                              <td>
                                <span className="data-chip mono">{it.ip || "—"}</span>
                                {it.is_attack_ip && (
                                  <span
                                    className="ml-1 text-rose-600"
                                    title="IP อยู่ใน blacklist"
                                  >
                                    ⚠
                                  </span>
                                )}
                              </td>
                              <td>
                                <div className="risk-cell">
                                  <div className="risk-track">
                                    <i className={tone} style={{ width: `${pct}%` }} />
                                  </div>
                                  <b className="mono">
                                    {it.risk_score != null ? it.risk_score.toFixed(2) : "—"}
                                  </b>
                                </div>
                              </td>
                              <td>
                                <span className={`decision ${tone}`}>
                                  <i />
                                  {(it.decision || "—").toUpperCase()}
                                </span>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <div className="feed-foot">
                    <span className="signal-dot">
                      <i />
                    </span>
                    ข้อมูลจาก /admin/activity · 24 ชั่วโมงล่าสุด
                    <b className="mono">{act.items.length} รายการ</b>
                  </div>
                </>
              )}
            </section>

            {/* 4-layer risk engine */}
            <section className="card risk-card">
              <div className="card-head">
                <div>
                  <span className="overline">4-layer risk engine</span>
                  <h2>การตัดสินใจ · 30 วัน</h2>
                </div>
              </div>
              {dec && decTotal > 0 ? (
                (() => {
                  const pAllow = (dec.allow / decTotal) * 100;
                  const pWatch = (dec.watch / decTotal) * 100;
                  const rows = [
                    { k: "allow", l: "Allow", v: dec.allow },
                    { k: "mfa", l: "Challenge / Warn", v: dec.watch },
                    { k: "block", l: "Block", v: dec.block },
                  ];
                  return (
                    <div className="donut-row">
                      <div
                        className="donut"
                        style={{
                          background: `conic-gradient(var(--sr-ok) 0 ${pAllow}%, var(--sr-warn) ${pAllow}% ${pAllow + pWatch}%, var(--sr-danger) ${pAllow + pWatch}% 100%)`,
                        }}
                        role="img"
                        aria-label={`สัดส่วนการตัดสินใจ: allow ${dec.allow}, challenge ${dec.watch}, block ${dec.block}`}
                      >
                        <div>
                          <strong className="mono">{decTotal.toLocaleString()}</strong>
                          <span>sessions</span>
                        </div>
                      </div>
                      <div className="donut-legend">
                        {rows.map((r) => (
                          <p key={r.k}>
                            <i className={r.k} />
                            {r.l}
                            <b className="mono">{r.v.toLocaleString()}</b>
                            <em className="mono">
                              {Math.round((r.v / decTotal) * 1000) / 10}%
                            </em>
                          </p>
                        ))}
                      </div>
                    </div>
                  );
                })()
              ) : (
                <div className="py-6 text-center text-sm text-ink-400">ยังไม่มีข้อมูล</div>
              )}
              <Link href="/ml" className="engine-status">
                <div>
                  <IconGauge />
                  Model runtime
                </div>
                <b>
                  <span className="signal-dot">
                    <i />
                  </span>
                  ดูรายละเอียด ML →
                </b>
              </Link>
            </section>
          </div>

          {/* ── risk distribution + security signals ── */}
          <div className="analytics-grid">
            <section className="card distribution-card">
              <div className="card-head chart-card-head">
                <div>
                  <span className="overline">risk distribution</span>
                  <h2>การกระจายคะแนนความเสี่ยง</h2>
                </div>
              </div>

              {!dist || !ins ? (
                <div className="py-8 text-center text-sm text-ink-400">กำลังโหลด…</div>
              ) : dist.scored_total === 0 ? (
                <div className="py-8 text-center text-sm text-ink-400">
                  ยังไม่มี session ที่ให้คะแนนใน 24 ชั่วโมงที่ผ่านมา
                </div>
              ) : (
                (() => {
                  const th = ins.risk.thresholds;
                  // แท่งวางบนแกน 0–1 จริง: ความกว้าง = ช่วงคะแนนของ band, ความสูง = จำนวน
                  // (ข้อมูลจริงมี 4 ช่วง ไม่ใช่ 20 ช่องแบบต้นแบบ — จึงกางตามช่วงจริงแทนการปั้นข้อมูล)
                  const bands = [
                    { k: "low", from: 0, to: th.warn, v: dist.low },
                    { k: "mid", from: th.warn, to: th.challenge, v: dist.medium },
                    { k: "high", from: th.challenge, to: th.block, v: dist.high },
                    { k: "crit", from: th.block, to: 1, v: dist.critical },
                  ];
                  const max = Math.max(...bands.map((b) => b.v), 1);
                  return (
                    <>
                      <div className="risk-distribution">
                        <div
                          className="histogram"
                          role="img"
                          aria-label={`การกระจายคะแนนความเสี่ยง พร้อมเส้น MFA ${th.challenge} และ Block ${th.block}`}
                        >
                          {bands.map((b) => (
                            <i
                              key={b.k}
                              className={b.k}
                              data-empty={b.v === 0 ? "true" : undefined}
                              style={{
                                height: `${Math.max((b.v / max) * 100, 3)}%`,
                                flex: `0 0 ${(b.to - b.from) * 100}%`,
                              }}
                              title={`คะแนน ${b.from}–${b.to}: ${b.v} session`}
                            />
                          ))}
                          <span
                            className="threshold mfa-line"
                            style={{ left: `${th.challenge * 100}%` }}
                          >
                            <b className="mono">MFA · {th.challenge}</b>
                          </span>
                          <span
                            className="threshold block-line"
                            style={{ left: `${th.block * 100}%` }}
                          >
                            <b className="mono">BLOCK · {th.block}</b>
                          </span>
                        </div>
                        <div className="histogram-axis mono">
                          <span>0.00</span>
                          <span>0.25</span>
                          <span>0.50</span>
                          <span>0.75</span>
                          <span>1.00</span>
                        </div>
                      </div>
                      <div className="risk-bands">
                        {bands.map((b) => (
                          <span key={b.k}>
                            <i className={b.k} />
                            {b.k === "low"
                              ? "Low"
                              : b.k === "mid"
                                ? "Medium"
                                : b.k === "high"
                                  ? "High"
                                  : "Critical"}
                            <b className="mono">{b.v}</b>
                          </span>
                        ))}
                      </div>
                    </>
                  );
                })()
              )}
            </section>

            <section className="card threat-card">
              <div className="card-head">
                <div>
                  <span className="overline">security signals</span>
                  <h2>สัญญาณความผิดปกติที่พบ</h2>
                </div>
                <IconAlert />
              </div>

              {!ins ? (
                <div className="py-8 text-center text-sm text-ink-400">กำลังโหลด…</div>
              ) : ins.signals.length === 0 ? (
                <div className="py-8 text-center text-sm text-ink-400">
                  ไม่พบสัญญาณผิดปกติใน 24 ชั่วโมงที่ผ่านมา
                </div>
              ) : (
                <div className="threat-bars">
                  {ins.signals.slice(0, 6).map((s, i) => (
                    <div key={s.key}>
                      <p>
                        <span title={s.key}>{s.label}</span>
                        <b className="mono">{s.count}</b>
                      </p>
                      <i>
                        <span
                          className={i === 0 ? "critical" : undefined}
                          style={{
                            width: `${(s.count / ins.signals[0].count) * 100}%`,
                          }}
                        />
                      </i>
                    </div>
                  ))}
                </div>
              )}

              {ins && (
                <div className="source-strip">
                  <IconAlert />
                  <div>
                    <span>Session จาก IP ใน blacklist</span>
                    <b className="mono">{ins.attack_ip.sessions} session</b>
                  </div>
                  {ins.attack_ip.pct !== null && (
                    <code className="mono">{ins.attack_ip.pct}%</code>
                  )}
                </div>
              )}
            </section>
          </div>

          {/* ── auth policy ── */}
          <LoginMethodsCard />
        </div>
      </main>
    </>
  );
}
