"use client";

/**
 * SOC Dashboard — ธีมกรมท่า (navy) + cyan, ศูนย์เฝ้าระวังการยืนยันตัวตน.
 *
 * โครงหน้าอิงดีไซน์ Signal Room: header → action required → KPI 5 ตัว →
 * กราฟ authentication traffic → แผนที่ + สถานะระบบย่อย → การเข้าใช้งานล่าสุด →
 * risk distribution + security signals → auth policy
 *
 * ข้อมูลจริงทั้งหมด ไม่มีค่าสมมติ:
 *   /admin/overview · /admin/users/count · /admin/dashboard/map
 *   /admin/notifications/count · /admin/dashboard/insights · /admin/activity
 *
 * กฎที่ยึด (B51): ค่าที่เป็น 0 จริงต้องแสดง 0 — เช็ค "ยังไม่โหลด" จาก source object
 * ห้ามใช้ `value || "—"` เพราะ 0 เป็น falsy จะกลายเป็น "—" ทั้งที่ข้อมูลมาแล้ว
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";
import { LoginMethodsCard } from "./_components/LoginMethodsCard";
import { AuthTopologyMap } from "./_components/AuthTopologyMap";

type Overview = {
  users: { total: number; active: number };
  subsystems: { total: number; active: number; pending: number };
  logins: { total: number; blocked: number };
};

type UserCount = Record<string, number>;

type NotifCount = {
  total: number;
  unread?: number;
  by_category: {
    approval_requests: number;
    ml_anomaly: number;
    api_alerts: number;
    subsystem_health: number;
  };
};

type MapData = {
  geo: { country: string; risk: "green" | "yellow" | "red"; count: number }[];
  decisions: Record<string, number>;
  subsystems: {
    id: string;
    name: string;
    status: string;
    health: string | null;
    latency_ms: number | null;
  }[];
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

const CATEGORY_LABELS: Record<string, { label: string; icon: string }> = {
  approval_requests: { label: "คำขอ Approve", icon: "📋" },
  ml_anomaly: { label: "ML Anomaly", icon: "🧠" },
  api_alerts: { label: "API Alerts", icon: "🛡️" },
  subsystem_health: { label: "Subsystem ล่ม", icon: "🟢" },
};

type HealthCheckResult = { ok: boolean; subsystems?: number };

const HEALTH_DOT: Record<string, string> = {
  online: "bg-emerald-400",
  degraded: "bg-amber-400",
  down: "bg-rose-400",
};

const DECISION_STYLE: Record<string, string> = {
  allow: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  warn: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  challenge: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  block: "border-rose-500/40 bg-rose-500/10 text-rose-300",
};

function decisionStyle(d: string | null) {
  if (!d) return "border-slate-600/40 bg-slate-700/20 text-slate-400";
  const key = d.replace("would_", "");
  return DECISION_STYLE[key] || "border-slate-600/40 bg-slate-700/20 text-slate-400";
}

/** จัดกลุ่ม decision → 3 ระดับสำหรับ bar */
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

function hourLabel(iso: string | null) {
  if (!iso) return "";
  return toDate(iso).toLocaleTimeString("th-TH", {
    timeZone: "Asia/Bangkok",
    hour: "2-digit",
    hour12: false,
  });
}

export default function DashboardPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [counts, setCounts] = useState<UserCount | null>(null);
  const [notif, setNotif] = useState<NotifCount | null>(null);
  const [map, setMap] = useState<MapData | null>(null);
  const [ins, setIns] = useState<Insights | null>(null);
  const [act, setAct] = useState<ActivityResp | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hcBusy, setHcBusy] = useState(false);
  const [hcResult, setHcResult] = useState<HealthCheckResult | null>(null);
  const [hcError, setHcError] = useState<string | null>(null);

  const refreshLive = () => {
    clientFetch<NotifCount>("/admin/notifications/count").then(setNotif).catch(() => {});
    clientFetch<MapData>("/admin/dashboard/map").then(setMap).catch(() => {});
    clientFetch<Insights>("/admin/dashboard/insights?hours=24").then(setIns).catch(() => {});
    clientFetch<ActivityResp>("/admin/activity?hours=24&limit=8").then(setAct).catch(() => {});
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
      clientFetch<UserCount>("/admin/users/count"),
      clientFetch<NotifCount>("/admin/notifications/count").catch(() => null),
      clientFetch<MapData>("/admin/dashboard/map").catch(() => null),
      clientFetch<Insights>("/admin/dashboard/insights?hours=24").catch(() => null),
      clientFetch<ActivityResp>("/admin/activity?hours=24&limit=8").catch(() => null),
    ])
      .then(([ov, ct, nc, mp, iv, ac]) => {
        setData(ov);
        setCounts(ct);
        if (nc) setNotif(nc);
        if (mp) setMap(mp);
        if (iv) setIns(iv);
        if (ac) setAct(ac);
      })
      .catch((e) => setError(e.detail || "โหลดข้อมูลไม่สำเร็จ"));

    const t = setInterval(refreshLive, 30_000);
    return () => clearInterval(t);
  }, []);

  const dec = map ? decisionGroups(map.decisions) : null;
  const decTotal = dec ? dec.allow + dec.watch + dec.block : 0;
  const onlineSubs = map?.subsystems.filter((s) => s.health === "online").length ?? 0;
  const downSubs = map?.subsystems.filter((s) => s.health === "down").length ?? 0;

  // KPI ที่ต้องคำนวณ — เช็คจาก source object ไม่ใช่ค่าที่คำนวณได้ (B51)
  const k = act?.kpis;
  const successPct =
    k && k.total > 0 ? Math.round(((k.total - k.blocked) / k.total) * 1000) / 10 : null;
  const highRisk = k ? k.blocked + k.challenged : null;
  const staffTotal = counts
    ? (counts.teacher ?? 0) + (counts.staff ?? 0) + (counts.admin ?? 0)
    : null;
  const peak = act?.hourly.length
    ? act.hourly.reduce((a, b) => (b.count > a.count ? b : a))
    : null;
  const blockedPeak = act?.hourly.length
    ? act.hourly.reduce((a, b) => (b.blocked > a.blocked ? b : a))
    : null;
  const maxBar = act?.hourly.length ? Math.max(...act.hourly.map((h) => h.count), 1) : 1;
  const dist = ins?.risk.distribution;

  return (
    <>
      <Topbar title="ภาพรวมระบบ" />
      {/* พื้นหลัง navy ครอบทั้งหน้า dashboard */}
      <main className="min-h-[calc(100vh-57px)] bg-[#0b1530] px-6 py-6 lg:px-8">
        <div className="max-w-7xl mx-auto w-full space-y-5">
          {error && (
            <div className="p-4 rounded-lg bg-rose-950/60 border border-rose-800 text-rose-200 text-sm">
              {error}
            </div>
          )}

          {/* ── header ── */}
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <div className="text-[11px] font-mono tracking-[0.25em] text-cyan-400/80 uppercase">
                Central Auth Hub · Security Monitor
              </div>
              <h1 className="text-xl font-extrabold text-white mt-0.5">
                ศูนย์เฝ้าระวังการยืนยันตัวตน
              </h1>
            </div>
            <div className="ml-auto flex items-center gap-3">
              {map && (
                <div className="hidden sm:flex items-center gap-2 text-xs font-mono text-slate-400">
                  <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                  {map.active_now} sessions online
                </div>
              )}
              <button
                onClick={runHealthCheckNow}
                disabled={hcBusy}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-cyan-500/15 border border-cyan-500/40 hover:bg-cyan-500/25 disabled:opacity-40 text-cyan-300 text-sm font-bold transition"
              >
                {hcBusy ? "กำลังตรวจ…" : "🩺 เช็คสุขภาพระบบ"}
              </button>
            </div>
          </div>

          {hcResult && hcResult.ok && (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-950/50 border border-emerald-700/60 text-emerald-300 text-xs">
              ✓ ตรวจเสร็จ — Hub + {hcResult.subsystems} subsystem
              <Link href="/notifications" className="ml-1 font-bold underline hover:no-underline">
                รายงาน →
              </Link>
            </div>
          )}
          {hcError && (
            <div className="px-3 py-2 rounded-lg bg-rose-950/50 border border-rose-800 text-rose-300 text-xs">
              ✗ {hcError}
            </div>
          )}

          {/* ── action required ── */}
          {notif && (notif.unread ?? 0) > 0 && (
            <Link
              href="/notifications"
              className="block rounded-xl border border-amber-500/50 bg-amber-500/10 p-4 hover:bg-amber-500/15 transition group"
            >
              <div className="flex items-center gap-3">
                <span className="text-2xl">🔔</span>
                <div className="flex-1">
                  <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-amber-500/80">
                    action required
                  </div>
                  <div className="text-sm font-extrabold text-amber-300">
                    มี {notif.unread} แจ้งเตือนยังไม่อ่าน
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {Object.entries(notif.by_category)
                      .filter(([, c]) => c > 0)
                      .map(([key, c]) => {
                        const info = CATEGORY_LABELS[key];
                        if (!info) return null;
                        return (
                          <span
                            key={key}
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-500/15 border border-amber-500/30 text-[11px] font-semibold text-amber-200"
                          >
                            {info.icon} {info.label}
                            <span className="font-mono">×{c}</span>
                          </span>
                        );
                      })}
                  </div>
                </div>
                <span className="text-amber-400 group-hover:translate-x-1 transition text-xl">
                  →
                </span>
              </div>
            </Link>
          )}

          {/* ── KPI strip ── */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
            {[
              {
                label: "ผู้ใช้ทั้งหมด",
                value: data ? data.users.total : "—",
                sub: ins
                  ? `+${ins.users.new_30d} ใน 30 วัน`
                  : staffTotal !== null
                    ? `บุคลากร ${staffTotal}`
                    : "—",
              },
              {
                label: "ระบบย่อย",
                value: data ? data.subsystems.active : "—",
                sub: data
                  ? `${data.subsystems.active} active · ${data.subsystems.pending} pending`
                  : "—",
              },
              {
                label: "Login · 24 ชม.",
                value: k ? k.total : "—",
                sub: successPct !== null ? `${successPct}% สำเร็จ` : "ยังไม่มีข้อมูล",
              },
              {
                label: "ความเสี่ยงสูง",
                value: highRisk !== null ? highRisk : "—",
                sub: k ? `${k.blocked} blocked · ${k.challenged} challenged` : "—",
                danger: (highRisk ?? 0) > 0,
              },
              {
                label: "คะแนนเสี่ยงเฉลี่ย",
                value: ins && ins.risk.avg_today !== null ? ins.risk.avg_today.toFixed(2) : "—",
                sub:
                  ins && ins.risk.delta !== null
                    ? `${ins.risk.delta >= 0 ? "สูงกว่า" : "ต่ำกว่า"}เมื่อวาน ${Math.abs(
                        ins.risk.delta
                      ).toFixed(2)}`
                    : "ไม่มีข้อมูลเทียบ",
              },
            ].map((c) => (
              <div
                key={c.label}
                className="rounded-xl border border-slate-700/60 bg-slate-900/50 px-4 py-3"
              >
                <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400">
                  {c.label}
                </div>
                <div
                  className={`text-2xl font-extrabold tabular-nums mt-0.5 ${
                    c.danger ? "text-rose-400" : "text-white"
                  }`}
                >
                  {c.value}
                </div>
                <div className="text-[10px] text-slate-500">{c.sub}</div>
              </div>
            ))}
          </div>

          {/* ── authentication traffic ── */}
          <section className="rounded-xl border border-slate-700/60 bg-slate-900/50">
            <div className="px-5 py-3.5 border-b border-slate-700/60 flex flex-wrap items-center gap-3">
              <div>
                <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-cyan-400/70">
                  authentication traffic
                </div>
                <h2 className="text-sm font-bold text-slate-200">
                  ปริมาณการยืนยันตัวตน
                  <span className="ml-2 text-[10px] font-mono text-slate-500">24 ชั่วโมง</span>
                </h2>
              </div>
              <div className="ml-auto flex items-center gap-3 text-[10px] font-mono text-slate-400">
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-sm bg-cyan-400" /> allow
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-sm bg-amber-400" /> challenge
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-sm bg-rose-400" /> block
                </span>
              </div>
            </div>

            {!act ? (
              <div className="h-48 grid place-items-center text-slate-500 text-sm">กำลังโหลด…</div>
            ) : act.hourly.length === 0 ? (
              <div className="h-48 grid place-items-center text-slate-500 text-sm">
                ยังไม่มีการเข้าใช้งานใน 24 ชั่วโมงที่ผ่านมา
              </div>
            ) : (
              <>
                <div className="px-5 pt-5 flex items-end gap-1 h-44">
                  {act.hourly.map((h, i) => {
                    const allow = Math.max(h.count - h.blocked - h.challenged, 0);
                    const pct = (n: number) => `${(n / maxBar) * 100}%`;
                    return (
                      <div
                        key={h.hour ?? i}
                        className="flex-1 flex flex-col justify-end h-full"
                        title={`${hourLabel(h.hour)}:00 — ${h.count} ครั้ง (challenge ${
                          h.challenged
                        } · block ${h.blocked})`}
                      >
                        <div
                          style={{ height: pct(h.blocked) }}
                          className="bg-rose-400 rounded-t-sm"
                        />
                        <div style={{ height: pct(h.challenged) }} className="bg-amber-400" />
                        <div style={{ height: pct(allow) }} className="bg-cyan-400/80" />
                      </div>
                    );
                  })}
                </div>
                <div className="px-5 pb-2 pt-1 flex gap-1 text-[9px] font-mono text-slate-600">
                  {act.hourly.map((h, i) => (
                    <div key={h.hour ?? i} className="flex-1 text-center truncate">
                      {i % 3 === 0 ? hourLabel(h.hour) : ""}
                    </div>
                  ))}
                </div>
                <div className="px-5 py-3 border-t border-slate-700/60 grid grid-cols-3 gap-3 text-xs">
                  <div>
                    <div className="text-[10px] font-mono uppercase text-slate-500">ช่วงสูงสุด</div>
                    <div className="text-slate-200 font-bold tabular-nums">
                      {peak ? `${hourLabel(peak.hour)}:00 · ${peak.count}` : "—"}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] font-mono uppercase text-slate-500">
                      เทียบเมื่อวาน
                    </div>
                    <div
                      className={`font-bold tabular-nums ${
                        ins?.logins.change_pct == null
                          ? "text-slate-500"
                          : ins.logins.change_pct >= 0
                            ? "text-emerald-400"
                            : "text-amber-400"
                      }`}
                    >
                      {ins?.logins.change_pct == null
                        ? "ไม่มีข้อมูลเทียบ"
                        : `${ins.logins.change_pct >= 0 ? "+" : ""}${ins.logins.change_pct}%`}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] font-mono uppercase text-slate-500">
                      Blocked สูงสุด
                    </div>
                    <div className="text-slate-200 font-bold tabular-nums">
                      {blockedPeak ? `${blockedPeak.blocked} ครั้ง` : "—"}
                    </div>
                  </div>
                </div>
              </>
            )}
          </section>

          {/* ── main: map + side panel ── */}
          <div className="grid lg:grid-cols-3 gap-5">
            <section className="lg:col-span-2 rounded-xl border border-slate-700/60 bg-slate-900/50 overflow-hidden">
              <div className="px-5 py-3.5 border-b border-slate-700/60 flex items-center justify-between">
                <h2 className="text-sm font-bold text-slate-200">
                  แผนที่การยืนยันตัวตน
                  <span className="ml-2 text-[10px] font-mono text-slate-500 uppercase">
                    login origins · 30 วัน
                  </span>
                </h2>
                <div className="flex items-center gap-3 text-[10px] font-mono text-slate-400">
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-emerald-400" /> online
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-amber-400" /> degraded
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-rose-400" /> down
                  </span>
                </div>
              </div>
              <div className="p-2">
                {map ? (
                  <AuthTopologyMap geo={map.geo} subsystems={map.subsystems} />
                ) : (
                  <div className="h-72 grid place-items-center text-slate-500 text-sm">
                    กำลังโหลดแผนที่…
                  </div>
                )}
              </div>
            </section>

            <div className="space-y-5">
              {/* subsystem link status */}
              <section className="rounded-xl border border-slate-700/60 bg-slate-900/50">
                <div className="px-5 py-3.5 border-b border-slate-700/60 flex items-center justify-between">
                  <h2 className="text-sm font-bold text-slate-200">การเชื่อมต่อระบบย่อย</h2>
                  <span className="text-[10px] font-mono text-slate-500">
                    {onlineSubs} online{downSubs > 0 && ` · ${downSubs} down`}
                  </span>
                </div>
                <div className="p-3 space-y-1.5">
                  {!map || map.subsystems.length === 0 ? (
                    <div className="text-sm text-slate-500 text-center py-4">ยังไม่มีระบบย่อย</div>
                  ) : (
                    map.subsystems
                      .filter((s) => s.status === "active")
                      .map((s) => (
                        <Link
                          key={s.id}
                          href={`/subsystems/${s.id}`}
                          className="flex items-center gap-3 px-3 py-2 rounded-lg border border-slate-700/50 hover:border-cyan-500/50 hover:bg-cyan-500/5 transition text-xs"
                        >
                          <span
                            className={`w-2 h-2 rounded-full shrink-0 ${
                              HEALTH_DOT[s.health || ""] || "bg-slate-500"
                            }`}
                          />
                          <span className="flex-1 text-slate-200 font-medium truncate">
                            {s.name}
                          </span>
                          <span className="font-mono text-slate-500">
                            {s.latency_ms != null ? `${s.latency_ms}ms` : s.health || "—"}
                          </span>
                        </Link>
                      ))
                  )}
                </div>
              </section>

              {/* decision distribution */}
              <section className="rounded-xl border border-slate-700/60 bg-slate-900/50 p-5">
                <h2 className="text-sm font-bold text-slate-200 mb-3">
                  ผลตัดสิน RBA
                  <span className="ml-2 text-[10px] font-mono text-slate-500 uppercase">
                    30 วัน
                  </span>
                </h2>
                {dec && decTotal > 0 ? (
                  <>
                    <div className="flex h-2.5 rounded-full overflow-hidden bg-slate-800">
                      <div
                        className="bg-emerald-400"
                        style={{ width: `${(dec.allow / decTotal) * 100}%` }}
                      />
                      <div
                        className="bg-amber-400"
                        style={{ width: `${(dec.watch / decTotal) * 100}%` }}
                      />
                      <div
                        className="bg-rose-400"
                        style={{ width: `${(dec.block / decTotal) * 100}%` }}
                      />
                    </div>
                    <div className="mt-3 space-y-1.5 text-xs">
                      {[
                        { label: "อนุญาต (allow)", v: dec.allow, dot: "bg-emerald-400" },
                        { label: "เฝ้าระวัง (warn / challenge)", v: dec.watch, dot: "bg-amber-400" },
                        { label: "บล็อก (block)", v: dec.block, dot: "bg-rose-400" },
                      ].map((r) => (
                        <div key={r.label} className="flex items-center gap-2">
                          <span className={`w-2 h-2 rounded-full ${r.dot}`} />
                          <span className="text-slate-300 flex-1">{r.label}</span>
                          <span className="font-mono text-slate-400 tabular-nums">{r.v}</span>
                          <span className="font-mono text-slate-600 w-10 text-right">
                            {Math.round((r.v / decTotal) * 100)}%
                          </span>
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="text-sm text-slate-500 text-center py-3">ยังไม่มีข้อมูล</div>
                )}
                <Link
                  href="/ml"
                  className="mt-3 inline-block text-[11px] font-bold text-cyan-400 hover:text-cyan-300"
                >
                  ดูรายละเอียด ML →
                </Link>
              </section>
            </div>
          </div>

          {/* ── การเข้าใช้งานล่าสุด ── */}
          <section className="rounded-xl border border-slate-700/60 bg-slate-900/50 overflow-hidden">
            <div className="px-5 py-3.5 border-b border-slate-700/60 flex items-center gap-3">
              <div>
                <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-cyan-400/70">
                  recent access
                </div>
                <h2 className="text-sm font-bold text-slate-200">การเข้าใช้งานล่าสุด</h2>
              </div>
              <Link
                href="/activity"
                className="ml-auto text-[11px] font-bold text-cyan-400 hover:text-cyan-300"
              >
                ดูทั้งหมด →
              </Link>
            </div>
            {!act ? (
              <div className="py-8 text-center text-slate-500 text-sm">กำลังโหลด…</div>
            ) : act.items.length === 0 ? (
              <div className="py-8 text-center text-slate-500 text-sm">
                ยังไม่มีการเข้าใช้งานใน 24 ชั่วโมงที่ผ่านมา
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-[10px] font-mono uppercase tracking-wider text-slate-500 border-b border-slate-700/60">
                      <th className="text-left font-medium px-5 py-2">เวลา</th>
                      <th className="text-left font-medium px-3 py-2">ผู้ใช้งาน</th>
                      <th className="text-left font-medium px-3 py-2">ระบบ</th>
                      <th className="text-left font-medium px-3 py-2">IP</th>
                      <th className="text-right font-medium px-3 py-2">risk</th>
                      <th className="text-left font-medium px-5 py-2">decision</th>
                    </tr>
                  </thead>
                  <tbody>
                    {act.items.map((it) => (
                      <tr
                        key={it.id}
                        className="border-b border-slate-800/60 last:border-0 hover:bg-slate-800/30"
                      >
                        <td className="px-5 py-2 font-mono tabular-nums text-slate-400">
                          {timeTH(it.created_at)}
                        </td>
                        <td className="px-3 py-2 text-slate-200 truncate max-w-[13rem]">
                          {it.user_email || it.full_name || "—"}
                        </td>
                        <td className="px-3 py-2 text-slate-400 truncate max-w-[10rem]">
                          {it.subsystem_name || "Hub"}
                        </td>
                        <td className="px-3 py-2 font-mono text-slate-500">
                          {it.ip || "—"}
                          {it.is_attack_ip && (
                            <span className="ml-1 text-rose-400" title="IP อยู่ใน blacklist">
                              ⚠
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right font-mono tabular-nums text-slate-300">
                          {it.risk_score != null ? it.risk_score.toFixed(2) : "—"}
                        </td>
                        <td className="px-5 py-2">
                          <span
                            className={`inline-block px-2 py-0.5 rounded border text-[10px] font-bold uppercase ${decisionStyle(
                              it.decision
                            )}`}
                          >
                            {it.decision || "—"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* ── risk distribution + security signals ── */}
          <div className="grid lg:grid-cols-2 gap-5">
            <section className="rounded-xl border border-slate-700/60 bg-slate-900/50 p-5">
              <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-cyan-400/70">
                risk distribution
              </div>
              <h2 className="text-sm font-bold text-slate-200">
                การกระจายคะแนนความเสี่ยง
                <span className="ml-2 text-[10px] font-mono text-slate-500">24 ชั่วโมง</span>
              </h2>

              {!dist || !ins ? (
                <div className="py-8 text-center text-slate-500 text-sm">กำลังโหลด…</div>
              ) : dist.scored_total === 0 ? (
                <div className="py-8 text-center text-slate-500 text-sm">
                  ยังไม่มี session ที่ให้คะแนนใน 24 ชั่วโมงที่ผ่านมา
                </div>
              ) : (
                <div className="mt-4 space-y-2.5">
                  {[
                    { label: "ต่ำ (allow)", v: dist.low, cls: "bg-emerald-400" },
                    {
                      label: `เฝ้าระวัง (≥ ${ins.risk.thresholds.warn})`,
                      v: dist.medium,
                      cls: "bg-cyan-400",
                    },
                    {
                      label: `สูง (≥ ${ins.risk.thresholds.challenge})`,
                      v: dist.high,
                      cls: "bg-amber-400",
                    },
                    {
                      label: `วิกฤต (≥ ${ins.risk.thresholds.block})`,
                      v: dist.critical,
                      cls: "bg-rose-400",
                    },
                  ].map((r) => (
                    <div key={r.label}>
                      <div className="flex items-center justify-between text-xs mb-1">
                        <span className="text-slate-300">{r.label}</span>
                        <span className="font-mono tabular-nums text-slate-400">
                          {r.v}
                          <span className="text-slate-600 ml-1.5">
                            {Math.round((r.v / dist.scored_total) * 100)}%
                          </span>
                        </span>
                      </div>
                      <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                        <div
                          className={`h-full ${r.cls}`}
                          style={{ width: `${(r.v / dist.scored_total) * 100}%` }}
                        />
                      </div>
                    </div>
                  ))}
                  <div className="pt-2 text-[10px] font-mono text-slate-600">
                    เกณฑ์จาก risk_aggregator · รวม {dist.scored_total} session
                  </div>
                </div>
              )}
            </section>

            <section className="rounded-xl border border-slate-700/60 bg-slate-900/50 p-5">
              <div className="text-[10px] font-mono uppercase tracking-[0.2em] text-cyan-400/70">
                security signals
              </div>
              <h2 className="text-sm font-bold text-slate-200">
                สัญญาณความผิดปกติที่พบ
                <span className="ml-2 text-[10px] font-mono text-slate-500">24 ชั่วโมง</span>
              </h2>

              {!ins ? (
                <div className="py-8 text-center text-slate-500 text-sm">กำลังโหลด…</div>
              ) : ins.signals.length === 0 ? (
                <div className="py-8 text-center text-slate-500 text-sm">
                  ไม่พบสัญญาณผิดปกติใน 24 ชั่วโมงที่ผ่านมา
                </div>
              ) : (
                <div className="mt-4 space-y-2">
                  {ins.signals.slice(0, 6).map((s) => (
                    <div key={s.key} className="flex items-center gap-3 text-xs">
                      <span className="text-slate-300 w-44 truncate" title={s.key}>
                        {s.label}
                      </span>
                      <div className="flex-1 h-1.5 rounded-full bg-slate-800 overflow-hidden">
                        <div
                          className="h-full bg-cyan-400/70"
                          style={{ width: `${(s.count / ins.signals[0].count) * 100}%` }}
                        />
                      </div>
                      <span className="font-mono tabular-nums text-slate-400 w-8 text-right">
                        {s.count}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {ins && (
                <div className="mt-4 pt-3 border-t border-slate-700/60 flex items-center justify-between text-xs">
                  <span className="text-slate-400">Session จาก IP ใน blacklist</span>
                  <span className="font-mono tabular-nums text-slate-200">
                    {ins.attack_ip.sessions}
                    {ins.attack_ip.pct !== null && (
                      <span className="text-slate-500 ml-1.5">{ins.attack_ip.pct}%</span>
                    )}
                  </span>
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
