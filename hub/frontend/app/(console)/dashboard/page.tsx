"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";
import { LoginMethodsCard } from "./_components/LoginMethodsCard";

type Overview = { users: { total: number; active: number }; subsystems: { total: number; active: number; pending: number }; logins: { total: number; blocked: number } };
type UserCount = Record<string, number>;
type NotifCount = { total: number; unread?: number; by_category: Record<string, number> };
type Subsystem = { id: string; name: string; status: string; health: string | null; latency_ms: number | null };
type MapData = { geo: { country: string; risk: string; count: number }[]; decisions: Record<string, number>; subsystems: Subsystem[]; active_now: number };
type ActivityItem = { id: string; created_at: string | null; user_email: string | null; subsystem_name: string | null; ip: string | null; risk_score: number | null; decision: string | null };
type ActivityData = { active: ActivityItem[]; items: ActivityItem[]; hourly: { hour: string | null; count: number; blocked: number }[]; kpis: { total: number; blocked: number; challenged: number; unique_users: number; avg_risk: number | null; online: number } };
type HealthCheckResult = { ok: boolean; subsystems?: number };

function groupDecisions(values: Record<string, number>) {
  const grouped = { allow: 0, mfa: 0, block: 0 };
  for (const [key, value] of Object.entries(values)) {
    if (key === "allow" || key === "mfa_passed") grouped.allow += value;
    else if (key.includes("block")) grouped.block += value;
    else grouped.mfa += value;
  }
  return grouped;
}

function toneForRisk(value: number) { return value >= .7 ? "crit" : value >= .4 ? "mid" : "low"; }

export default function DashboardPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [counts, setCounts] = useState<UserCount | null>(null);
  const [notifications, setNotifications] = useState<NotifCount | null>(null);
  const [map, setMap] = useState<MapData | null>(null);
  const [activity, setActivity] = useState<ActivityData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [checked, setChecked] = useState(false);

  const loadLive = () => Promise.all([
    clientFetch<NotifCount>("/admin/notifications/count").catch(() => null),
    clientFetch<MapData>("/admin/dashboard/map").catch(() => null),
    clientFetch<ActivityData>("/admin/activity?hours=24&limit=20").catch(() => null),
  ]).then(([nc, mp, ac]) => { if (nc) setNotifications(nc); if (mp) setMap(mp); if (ac) setActivity(ac); });

  useEffect(() => {
    Promise.all([clientFetch<Overview>("/admin/overview"), clientFetch<UserCount>("/admin/users/count")])
      .then(([ov, ct]) => { setOverview(ov); setCounts(ct); return loadLive(); })
      .catch((e) => setError(e?.detail || "โหลดข้อมูลไม่สำเร็จ"));
    const timer = setInterval(loadLive, 30_000);
    return () => clearInterval(timer);
  }, []);

  async function healthCheck() {
    setChecking(true); setChecked(false);
    try { await clientFetch<HealthCheckResult>("/admin/subsystems/health/emit-summary-now", { method: "POST" }); await loadLive(); setChecked(true); }
    catch (e) { setError((e as { detail?: string })?.detail || "ตรวจสุขภาพระบบไม่สำเร็จ"); }
    finally { setChecking(false); }
  }

  const decisions = useMemo(() => groupDecisions(map?.decisions || {}), [map]);
  const decisionTotal = decisions.allow + decisions.mfa + decisions.block;
  const activeSubsystems = map?.subsystems.filter((s) => s.status === "active") || [];
  const liveEvents = [...(activity?.active || []), ...(activity?.items || [])].slice(0, 4);
  const averageRisk = activity?.kpis.avg_risk;

  return <>
    <Topbar title="ภาพรวมระบบ" />
    <section className="command-bar">
      <div className="command-copy"><div className="live-label"><Signal /> LIVE CONTROL SURFACE</div><h1>ภาพรวมระบบ</h1></div>
      <div className="command-actions">
        <div className="health-stamp"><ShieldIcon /><div><span>SYSTEM STATUS</span><strong>{error ? "ต้องตรวจสอบ" : "ระบบพร้อมทำงาน"}</strong></div></div>
        <button className={`refresh ${checking ? "spin" : ""}`} onClick={healthCheck} disabled={checking}><RefreshIcon />{checking ? "กำลังตรวจ..." : checked ? "อัปเดตแล้ว" : "ตรวจสุขภาพ"}</button>
      </div>
      <div className="signal-rule" />
    </section>

    <main className="document dashboard-document">
      {error && <section className="attention-banner"><div className="attention-icon">!</div><div><span className="overline">CONNECTION NOTICE</span><strong>{error}</strong><p>ตรวจสอบ backend และลองรีเฟรชอีกครั้ง</p></div></section>}
      {!error && notifications && (notifications.unread ?? 0) > 0 && <Link href="/notifications" className="attention-banner">
        <div className="attention-icon">!</div><div><span className="overline">ACTION REQUIRED</span><strong>มี {notifications.unread} รายการที่รอการตรวจสอบ</strong><p>รวมคำขออนุมัติ เหตุการณ์ ML และการแจ้งเตือน API</p></div><b>เปิดรายการงาน →</b>
      </Link>}

      <section className="kpi-grid" aria-label="สรุปสถานะระบบ">
        <Kpi label="USERS TOTAL" value={overview?.users.total} meta={`${overview?.users.active ?? 0} active`} tone="signal-kpi" />
        <Kpi label="STUDENTS" value={counts?.student} meta="identity directory" />
        <Kpi label="SUBSYSTEMS" value={overview?.subsystems.total} meta={`${overview?.subsystems.active ?? 0} active · ${overview?.subsystems.pending ?? 0} pending`} />
        <Kpi label="LOGINS · 24H" value={activity?.kpis.total} meta={`${activity?.kpis.unique_users ?? 0} unique users`} />
        <Kpi label="HIGH RISK" value={(activity?.kpis.blocked ?? 0) + (activity?.kpis.challenged ?? 0)} meta={`${activity?.kpis.blocked ?? 0} blocked`} tone="risk-kpi" />
      </section>

      <section className="security-overview-grid">
        <article className="card auth-volume-card">
          <header className="card-head chart-card-head"><div><span className="overline">AUTHENTICATION TRAFFIC</span><h2>ปริมาณการยืนยันตัวตน · 24 ชั่วโมง</h2><p>ข้อมูลจริงจาก Login Sessions แยกผลปกติและรายการที่ถูกบล็อก</p></div><div className="chart-legend"><span><i className="allow"/>ทั้งหมด</span><span><i className="block"/>Block</span></div></header>
          <AuthVolumeChart rows={activity?.hourly || []} />
          <div className="chart-summary"><div><span>รวม 24 ชั่วโมง</span><b className="mono">{activity?.kpis.total ?? "—"} logins</b></div><div><span>ออนไลน์ตอนนี้</span><b className="positive mono">{map?.active_now ?? "—"} sessions</b></div><div><span>Blocked</span><b className="danger-text mono">{activity?.kpis.blocked ?? "—"} events</b></div></div>
        </article>

        <article className="card subsystem-card">
          <div className="subsystem-head"><div><span className="overline">SERVICE HEALTH MATRIX</span><h2>การเชื่อมต่อระบบย่อย</h2><p>สถานะ endpoint และ response time ล่าสุด</p></div><div className="matrix-health"><Signal/><span><b className="mono">{activeSubsystems.filter((s) => s.health === "online").length} / {activeSubsystems.length}</b> healthy</span></div></div>
          <div className="matrix-labels mono"><span>SERVICE</span><span>STATUS</span><span>LATENCY</span></div>
          <div className="service-matrix">{activeSubsystems.length ? activeSubsystems.slice(0, 4).map((service, index) => <Link href={`/subsystems/${service.id}`} className="service-row" key={service.id}>
            <div className="service-index mono"><span>{String(index + 1).padStart(2, "0")}</span><i/></div><div className="service-name"><strong>{service.name}</strong><span className="mono">OAuth client</span></div><div className="uptime-value"><b className="mono">{service.health || "unknown"}</b><span>{service.status}</span></div><div className="latency-value"><b className="mono">{service.latency_ms ?? "—"} <small>ms</small></b><span className={`latency-state ${(service.latency_ms ?? 0) < 500 ? "fast" : "watch"}`}>{(service.latency_ms ?? 0) < 500 ? "normal" : "watch"}</span></div>
          </Link>) : <div className="subsystem-empty">ยังไม่มีระบบย่อย</div>}</div>
          <div className="subsystem-foot"><span>ตรวจอัตโนมัติทุก <b className="mono">30s</b></span><code className="mono">LIVE DATA</code></div>
        </article>
      </section>

      <section className="main-grid">
        <article className="card activity-card">
          <header className="card-head"><div><div className="title-row"><Signal/><h2>การเข้าใช้งานล่าสุด</h2><span className="live-chip mono">LIVE</span></div><p>เหตุการณ์ยืนยันตัวตนจากทุกระบบย่อย</p></div><Link className="link-button" href="/activity">ดู Realtime ทั้งหมด →</Link></header>
          <div className="table-wrap"><table><thead><tr><th>เวลา</th><th>ผู้ใช้งาน</th><th>ระบบ</th><th>IP ADDRESS</th><th>RISK SCORE</th><th>DECISION</th></tr></thead><tbody>{liveEvents.length ? liveEvents.map((event) => { const risk = event.risk_score ?? 0; const tone = toneForRisk(risk); return <tr key={event.id}><td className="mono time-cell">{formatTime(event.created_at)}</td><td className="mono email-cell">{event.user_email || "—"}</td><td>{event.subsystem_name || "Hub"}</td><td><span className="data-chip mono">{event.ip || "—"}</span></td><td><RiskMeter value={risk} tone={tone}/></td><td><span className={`decision ${tone}`}><i/>{(event.decision || "unknown").toUpperCase()}</span></td></tr>; }) : <tr><td colSpan={6} className="empty-table">ยังไม่มีข้อมูลการเข้าสู่ระบบ</td></tr>}</tbody></table></div>
          <div className="feed-foot"><Signal/><span>เชื่อมต่อข้อมูลจริงแล้ว</span><b className="mono">refresh 30s</b></div>
        </article>

        <article className="card risk-card">
          <header className="card-head"><div><span className="overline">4-LAYER RISK ENGINE</span><h2>การตัดสินใจ · 30 วัน</h2></div></header>
          <div className="donut-row"><div className="donut" style={{background: donutGradient(decisions, decisionTotal)}}><div><strong className="mono">{decisionTotal}</strong><span>sessions</span></div></div><div className="donut-legend"><LegendRow tone="allow" label="Allow" value={decisions.allow} total={decisionTotal}/><LegendRow tone="mfa" label="MFA / Warn" value={decisions.mfa} total={decisionTotal}/><LegendRow tone="block" label="Block" value={decisions.block} total={decisionTotal}/></div></div>
          <div className="engine-status"><div><span>Model runtime</span></div><b><Signal/>ONLINE</b><code className="mono">shadow mode · real sessions</code></div>
        </article>
      </section>

      <section className="analytics-grid">
        <article className="card distribution-card"><header className="card-head"><div><span className="overline">RISK DISTRIBUTION</span><h2>การกระจายคะแนนความเสี่ยง</h2><p>คำนวณจากรายการ Session ล่าสุดที่ backend ส่งกลับ</p></div></header><RiskDistribution rows={liveEvents}/><div className="risk-bands"><span><i className="low"/>Low <b className="mono">0.00–0.39</b></span><span><i className="mid"/>Medium <b className="mono">0.40–0.59</b></span><span><i className="high"/>High <b className="mono">0.60–0.84</b></span><span><i className="crit"/>Critical <b className="mono">0.85–1.00</b></span></div></article>
        <article className="card threat-card"><header className="card-head"><div><span className="overline">SECURITY SIGNALS</span><h2>รายการที่ต้องตรวจสอบ</h2><p>สรุปจาก Notification Center</p></div></header><div className="threat-bars">{Object.entries(notifications?.by_category || {}).map(([name, value]) => <div key={name}><p><span>{categoryName(name)}</span><b className="mono">{value}</b></p><i><span style={{width: `${Math.min(100, value * 12)}%`}}/></i></div>)}{!notifications && <p className="empty-signals">กำลังโหลดข้อมูล</p>}</div><div className="source-strip"><div><span>ค่าเฉลี่ยความเสี่ยงล่าสุด</span><b>Risk Engine</b></div><code className="mono">{averageRisk == null ? "—" : averageRisk.toFixed(3)}</code></div></article>
      </section>

      <LoginMethodsCard />
      <footer><span>Central Auth Hub</span><code className="mono">OAUTH 2.0 · OIDC · RBAC · RBA</code><span><Signal/>System operational</span></footer>
    </main>
  </>;
}

function Kpi({ label, value, meta, tone = "" }: { label: string; value?: number; meta: string; tone?: string }) { return <article className={`kpi ${tone}`}><div className="kpi-head"><span>{label}</span></div><strong className="mono">{value ?? "—"}</strong><p>{meta}</p></article>; }
function Signal() { return <span className="signal-dot" aria-hidden="true"><i /></span>; }
function ShieldIcon() { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M12 3 20 6v5.5c0 5-3.1 8.1-8 9.5-4.9-1.4-8-4.5-8-9.5V6l8-3Z"/><path d="m8.5 12 2.2 2.2 4.8-5"/></svg>; }
function RefreshIcon() { return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 8a7 7 0 0 1 11.8-1l2.1 5M17.9 16A7 7 0 0 1 6.1 17L4 12"/></svg>; }
function formatTime(value: string | null) { if (!value) return "—"; const date = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`); return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString("th-TH", { timeZone: "Asia/Bangkok", hour12: false }); }
function RiskMeter({ value, tone }: { value: number; tone: string }) { return <div className="risk-cell"><div className="risk-track"><i className={tone} style={{width: `${Math.min(100, value * 100)}%`}}/></div><b className="mono">{value.toFixed(2)}</b></div>; }
function LegendRow({ tone, label, value, total }: { tone: string; label: string; value: number; total: number }) { return <p><i className={tone}/><span>{label}</span><b className="mono">{value}</b><em>{total ? Math.round(value / total * 100) : 0}%</em></p>; }
function donutGradient(d: { allow: number; mfa: number; block: number }, total: number) { if (!total) return "conic-gradient(#e8edf1 0 100%)"; const allow = d.allow / total * 100; const mfa = (d.allow + d.mfa) / total * 100; return `conic-gradient(var(--ok) 0 ${allow}%,var(--warn) ${allow}% ${mfa}%,var(--danger) ${mfa}% 100%)`; }
function categoryName(key: string) { return ({ approval_requests: "คำขออนุมัติ", ml_anomaly: "ML anomaly", api_alerts: "API alerts", subsystem_health: "Subsystem health" } as Record<string, string>)[key] || key.replaceAll("_", " "); }

function AuthVolumeChart({ rows }: { rows: ActivityData["hourly"] }) {
  const source = rows.slice(-24); const max = Math.max(1, ...source.map((r) => r.count));
  return <div className="volume-chart" role="img" aria-label="ปริมาณการยืนยันตัวตนรายชั่วโมง"><div className="chart-y"><span>{max}</span><span>{Math.round(max*.75)}</span><span>{Math.round(max*.5)}</span><span>{Math.round(max*.25)}</span><span>0</span></div><div className="bar-plot">{(source.length ? source : Array.from({length: 12}, (_, i) => ({hour: `${i*2}:00`, count: 0, blocked: 0}))).filter((_, i, a) => a.length <= 12 || i % 2 === 0).map((item, index) => <div className="hour-column" key={`${item.hour}-${index}`}><div className="stacked-bar"><i className="bar-block" style={{height: `${item.blocked / max * 100}%`}}/><i className="bar-allow" style={{height: `${Math.max(2, (item.count-item.blocked) / max * 100)}%`}}/></div><span className="mono">{item.hour?.slice(0, 2) ?? "--"}</span></div>)}</div></div>;
}

function RiskDistribution({ rows }: { rows: ActivityItem[] }) {
  const buckets = Array.from({length: 20}, () => 0); rows.forEach((row) => { const score = Math.max(0, Math.min(.999, row.risk_score ?? 0)); buckets[Math.floor(score*20)] += 1; }); const max = Math.max(1, ...buckets);
  return <div className="risk-distribution"><div className="histogram">{buckets.map((count, index) => <i key={index} className={index >= 17 ? "crit" : index >= 12 ? "high" : index >= 8 ? "mid" : "low"} style={{height: `${Math.max(count ? 8 : 2, count/max*100)}%`}}/>)}<span className="threshold mfa-line"><b className="mono">MFA · 0.60</b></span><span className="threshold block-line"><b className="mono">BLOCK · 0.85</b></span></div><div className="histogram-axis mono"><span>0.00</span><span>0.25</span><span>0.50</span><span>0.75</span><span>1.00</span></div></div>;
}
