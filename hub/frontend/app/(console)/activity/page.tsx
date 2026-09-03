"use client";

/**
 * Access Activity — realtime login feed (email-centric).
 * แสดง: ใคร · ระบบย่อยไหน · ช่องทาง · ML/risk · decision · ที่ไหน · device · เมื่อไหร่
 * Aesthetic: "Mission Control" — dark control bar + light data board + live pulse.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { LineChart } from "@/components/LineChart";
import { clientFetch } from "@/lib/api";

type Activity = {
  id: string;
  created_at: string | null;
  user_email: string | null;
  full_name: string | null;
  user_type: string | null;
  subsystem_id: string | null;
  subsystem_name: string | null;
  login_method: string | null;
  anomaly_score: number | null;
  risk_score: number | null;
  decision: string | null;
  ip: string | null;
  geo_country: string | null;
  geo_city: string | null;
  browser: string | null;
  os_name: string | null;
  device_type: string | null;
  is_attack_ip: boolean;
  logout_at: string | null;
  online_seconds?: number;
  session_kind?: "hub" | "subsystem";
  session_expires_at?: string | null;
};

type HourBucket = { hour: string | null; count: number; blocked: number };

type ActivityResponse = {
  active: Activity[];
  active_count: number;
  items: Activity[];
  total: number;
  window_hours: number;
  kpis: {
    total: number;
    blocked: number;
    challenged: number;
    unique_users: number;
    avg_risk: number | null;
    online: number;
  };
  channels: Record<string, number>;
  hourly: HourBucket[];
};

type SubsystemLite = { id: string; name: string };

const WINDOWS = [
  { h: 1, label: "1 ชม." },
  { h: 24, label: "24 ชม." },
  { h: 168, label: "7 วัน" },
  { h: 720, label: "30 วัน" },
];

const CHANNEL_META: Record<string, { icon: string; label: string; cls: string }> = {
  google: { icon: "🔵", label: "Google", cls: "bg-blue-50 text-blue-700 border-blue-200" },
  passkey: { icon: "🔑", label: "Passkey", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  discoverable: { icon: "🔓", label: "Passkey", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  line: { icon: "🟢", label: "LINE", cls: "bg-green-50 text-green-700 border-green-200" },
  hub_direct: { icon: "🏛️", label: "Hub", cls: "bg-ink-100 text-ink-600 border-ink-200" },
  unknown: { icon: "•", label: "—", cls: "bg-ink-100 text-ink-400 border-ink-200" },
};

function channelMeta(m: string | null) {
  return CHANNEL_META[m || "unknown"] || CHANNEL_META.unknown;
}
function decisionBadge(d: string | null): { label: string; cls: string } {
  switch (d) {
    case "allow":
      return { label: "ผ่าน", cls: "bg-emerald-100 text-emerald-800" };
    case "warn":
      return { label: "เฝ้าระวัง", cls: "bg-amber-100 text-amber-800" };
    case "challenge":
    case "mfa":
      return { label: "MFA", cls: "bg-orange-100 text-orange-800" };
    case "block":
      return { label: "บล็อก", cls: "bg-rose-100 text-rose-800" };
    case "would_block":
      return { label: "would-block", cls: "bg-rose-50 text-rose-600 border border-rose-200" };
    case "would_mfa":
    case "would_challenge":
      return { label: "would-mfa", cls: "bg-orange-50 text-orange-600 border border-orange-200" };
    default:
      return { label: d || "—", cls: "bg-ink-100 text-ink-500" };
  }
}

// risk 0..1 → สี
function riskColor(r: number): string {
  if (r >= 0.85) return "#e11d48"; // rose-600
  if (r >= 0.6) return "#f97316"; // orange-500
  if (r >= 0.3) return "#f59e0b"; // amber-500
  return "#10b981"; // emerald-500
}

function fmtRel(iso: string | null): string {
  if (!iso) return "—";
  const hasTz = /[+-]\d{2}:?\d{2}$|Z$/i.test(iso);
  const t = new Date(hasTz ? iso : iso + "Z").getTime();
  const diff = (Date.now() - t) / 1000;
  if (diff < 10) return "เมื่อกี้";
  if (diff < 60) return `${Math.floor(diff)} วิ`;
  if (diff < 3600) return `${Math.floor(diff / 60)} นาที`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} ชม.`;
  return `${Math.floor(diff / 86400)} วัน`;
}

// ระยะเวลาออนไลน์ — คำนวณสดจาก created_at
function fmtDuration(iso: string | null): string {
  if (!iso) return "—";
  const hasTz = /[+-]\d{2}:?\d{2}$|Z$/i.test(iso);
  const t = new Date(hasTz ? iso : iso + "Z").getTime();
  let s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  const h = Math.floor(s / 3600);
  s -= h * 3600;
  const m = Math.floor(s / 60);
  s -= m * 60;
  if (h > 0) return `${h}ชม ${m}น`;
  if (m > 0) return `${m}น ${s}ว`;
  return `${s}ว`;
}

function fmtClock(iso: string | null): string {
  if (!iso) return "";
  const hasTz = /[+-]\d{2}:?\d{2}$|Z$/i.test(iso);
  return new Date(hasTz ? iso : iso + "Z").toLocaleString("th-TH", {
    timeZone: "Asia/Bangkok",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function avatarColor(email: string | null): string {
  const s = email || "?";
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
  return `hsl(${h} 55% 45%)`;
}

export default function ActivityPage() {
  const [data, setData] = useState<ActivityResponse | null>(null);
  const [subsystems, setSubsystems] = useState<SubsystemLite[]>([]);
  const [error, setError] = useState<string | null>(null);

  // filters
  const [hours, setHours] = useState(24);
  const [q, setQ] = useState("");
  const [decision, setDecision] = useState("");
  const [channel, setChannel] = useState("");
  const [subId, setSubId] = useState("");

  // live
  const [live, setLive] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const seenIds = useRef<Set<string>>(new Set());
  const [freshIds, setFreshIds] = useState<Set<string>>(new Set());
  // ticker — re-render ทุก 1 วิ ให้ระยะเวลาออนไลน์เดินสด
  const [, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);

  const qs = useCallback(() => {
    const p = new URLSearchParams();
    p.set("hours", String(hours));
    p.set("limit", "80");
    if (q.trim()) p.set("q", q.trim());
    if (decision) p.set("decision", decision);
    if (channel) p.set("channel", channel);
    if (subId) p.set("subsystem_id", subId);
    return p.toString();
  }, [hours, q, decision, channel, subId]);

  const load = useCallback(
    (markFresh: boolean) => {
      clientFetch<ActivityResponse>(`/admin/activity?${qs()}`)
        .then((d) => {
          if (markFresh) {
            const fresh = new Set<string>();
            for (const it of d.items) {
              if (!seenIds.current.has(it.id)) fresh.add(it.id);
            }
            // ครั้งแรก (seen ว่าง) ไม่ highlight ทั้งหมด
            if (seenIds.current.size > 0 && fresh.size > 0) {
              setFreshIds(fresh);
              setTimeout(() => setFreshIds(new Set()), 2500);
            }
          }
          seenIds.current = new Set(d.items.map((i) => i.id));
          setData(d);
          setLastUpdated(new Date());
          setError(null);
        })
        .catch((e) => setError((e as { detail?: string })?.detail || "โหลดไม่สำเร็จ"));
    },
    [qs]
  );

  // โหลดเมื่อ filter เปลี่ยน (reset highlight baseline)
  useEffect(() => {
    seenIds.current = new Set();
    load(false);
  }, [load]);

  // auto-refresh
  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => load(true), 8000);
    return () => clearInterval(t);
  }, [live, load]);

  // subsystems for dropdown
  useEffect(() => {
    clientFetch<{ items?: SubsystemLite[] } | SubsystemLite[]>("/admin/subsystems")
      .then((r) => {
        const arr = Array.isArray(r) ? r : r.items || [];
        setSubsystems(arr.map((s) => ({ id: s.id, name: s.name })));
      })
      .catch(() => {});
  }, []);

  const k = data?.kpis;
  // stale = โหลดรอบล่าสุดพลาด แต่ยังมี data เก่าค้างอยู่ → เตือนว่าไม่ใช่ realtime
  // (กันเข้าใจผิดว่า pulse เขียว = คนออนไลน์จริงตอนนี้ ทั้งที่ fetch ค้างไปแล้ว)
  const stale = !!error && !!data;

  const controls = (
    <div className="cx-live-actions">
      <button
        type="button"
        className={live ? "cx-chip signal" : "cx-chip outline"}
        onClick={() => setLive((value) => !value)}
        aria-pressed={live}
      >
        <i className={live ? "cx-dot" : "cx-dot warn"}><i /></i>
        {live ? "LIVE" : "PAUSED"}
      </button>
      {WINDOWS.map((window) => (
        <button
          key={window.h}
          type="button"
          className={hours === window.h ? "active" : ""}
          onClick={() => setHours(window.h)}
        >
          {window.h === 1 ? "1h" : window.h === 24 ? "24h" : window.h === 168 ? "7d" : "30d"}
        </button>
      ))}
      <button type="button" onClick={() => load(false)} aria-label="รีเฟรชข้อมูล">
        ↻ รีเฟรช
      </button>
    </div>
  );

  return (
    <>
      <Topbar title="การเข้าใช้งาน (Realtime)" actions={controls} />

      <main className="cx-document cx-activity-page">
        {error && !data && (
          <div className="cx-alert danger" role="alert">{error}</div>
        )}

        <section className="cx-kpis five" aria-label="สรุปการเข้าใช้งาน">
          <Kpi label="ACTIVE SESSIONS" value={data?.active_count ?? "—"} sub="ONLINE NOW" tone="signal" />
          <Kpi label="TOTAL LOGINS" value={k?.total ?? "—"} sub={`${hours} HOURS`} />
          <Kpi label="BLOCKED" value={k?.blocked ?? "—"} sub="BLOCK / WOULD-BLOCK" tone="danger" />
          <Kpi label="MFA" value={k?.challenged ?? "—"} sub="CHALLENGE / MFA" />
          <Kpi
            label="AVG RISK"
            value={k?.avg_risk != null ? k.avg_risk.toFixed(2) : "—"}
            sub="RISK SCORE"
            tone={(k?.avg_risk ?? 0) >= 0.6 ? "danger" : undefined}
          />
        </section>

        <section className={`cx-panel cx-active-panel ${stale ? "is-stale" : ""}`}>
          <header>
            <div>
              <span className="mono">ACTIVE USERS · REALTIME</span>
              <h2>ผู้ใช้ที่กำลังใช้งาน</h2>
            </div>
            <span className="cx-chip signal"><i className="cx-dot"><i /></i>LIVE · {data?.active_count ?? 0}</span>
          </header>
          <div className="cx-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>USER</th>
                  <th>SYSTEM / SESSION</th>
                  <th>CHANNEL</th>
                  <th>LOCATION / IP</th>
                  <th>ONLINE FOR</th>
                  <th>RISK</th>
                </tr>
              </thead>
              <tbody>
                {!data && <EmptyRow cols={6} label="กำลังโหลดข้อมูล" />}
                {data && data.active.length === 0 && <EmptyRow cols={6} label="ไม่มีผู้ใช้งานออนไลน์" />}
                {data?.active.map((item) => {
                  const channelInfo = channelMeta(item.login_method);
                  const risk = item.risk_score ?? item.anomaly_score ?? 0;
                  return (
                    <tr key={item.id}>
                      <td>
                        <div className="cx-person">
                          <span style={{ background: avatarColor(item.user_email) }}>
                            {(item.full_name || item.user_email || "?")[0]?.toUpperCase()}
                          </span>
                          <b>{item.user_email || "—"}<small>{item.full_name || "ไม่ระบุชื่อ"}{item.user_type ? ` · ${item.user_type}` : ""}</small></b>
                        </div>
                      </td>
                      <td>
                        <b>{item.subsystem_name || "Hub-direct"}</b>
                        <small className="cx-data">{item.session_kind === "subsystem" ? "SUBSYSTEM SESSION" : "HUB SESSION"}</small>
                      </td>
                      <td><span className="cx-chip outline">{channelInfo.label}</span></td>
                      <td>
                        <span className="cx-data">{[item.geo_city, item.geo_country].filter(Boolean).join(", ") || "ไม่ทราบตำแหน่ง"}</span>
                        <code>{item.ip || "—"}</code>
                      </td>
                      <td>
                        <b>{fmtDuration(item.created_at)}</b>
                        <small className="cx-data">{item.session_kind === "hub" ? "ONLINE" : "SESSION VALID"}</small>
                      </td>
                      <td><Risk value={risk} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        <section className="cx-panel">
          <header>
            <div>
              <span className="mono">HOURLY VOLUME · LINE CHART</span>
              <h2>{chartTitle(hours)}</h2>
            </div>
            <span className="cx-data">{lastUpdated ? `UPDATED ${lastUpdated.toLocaleTimeString("th-TH", { hour12: false })}` : "WAITING FOR API"}</span>
          </header>
          <div className="cx-line-chart">
            <HourlyChart
              hourly={data?.hourly ?? []}
              activities={[...(data?.active ?? []), ...(data?.items ?? [])]}
              hours={hours}
            />
          </div>
        </section>

        <section className="cx-panel">
          <header>
            <div>
              <span className="mono">AUTH HISTORY</span>
              <h2>ประวัติการเข้าใช้งาน</h2>
            </div>
            <span className="cx-data">{data ? `${data.items.length} / ${data.total} RECORDS` : "WAITING FOR API"}</span>
          </header>

          <div className="cx-toolbar">
            <label>
              <SearchIcon />
              <input value={q} onChange={(event) => setQ(event.target.value)} placeholder="อีเมล, IP, อุปกรณ์..." />
            </label>
            <Select value={decision} onChange={setDecision} placeholder="ทุก decision">
              {["allow", "warn", "challenge", "mfa", "block", "would_block", "would_mfa"].map((item) => <option key={item} value={item}>{item}</option>)}
            </Select>
            <Select value={channel} onChange={setChannel} placeholder="ทุกช่องทาง">
              {["google", "passkey", "discoverable", "line", "hub_direct"].map((item) => <option key={item} value={item}>{item}</option>)}
            </Select>
            <Select value={subId} onChange={setSubId} placeholder="ทุกระบบ">
              <option value="hub">Hub-direct</option>
              {subsystems.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </Select>
            {(q || decision || channel || subId) && (
              <button type="button" onClick={() => { setQ(""); setDecision(""); setChannel(""); setSubId(""); }}>ล้างตัวกรอง</button>
            )}
          </div>

          <div className="cx-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>TIME</th>
                  <th>USER</th>
                  <th>CHANNEL</th>
                  <th>GEO / DEVICE</th>
                  <th>RISK</th>
                  <th>DECISION</th>
                </tr>
              </thead>
              <tbody>
                {!data && <EmptyRow cols={6} label="กำลังโหลดข้อมูล" />}
                {data && data.items.length === 0 && <EmptyRow cols={6} label="ไม่พบประวัติการเข้าใช้งาน" />}
                {data?.items.map((item) => {
                  const channelInfo = channelMeta(item.login_method);
                  const decisionInfo = decisionBadge(item.decision);
                  const risk = item.risk_score ?? item.anomaly_score ?? 0;
                  return (
                    <tr key={item.id} className={freshIds.has(item.id) ? "is-fresh" : ""}>
                      <td><b>{fmtRel(item.created_at)}</b><small className="cx-data">{fmtClock(item.created_at)}</small></td>
                      <td>
                        <b>{item.user_email || "—"}</b>
                        <small className="cx-data">{item.full_name || "ไม่ระบุชื่อ"} · {item.subsystem_name || "Hub-direct"}</small>
                      </td>
                      <td><span className="cx-chip outline">{channelInfo.label}</span></td>
                      <td>
                        <span>{[item.geo_city, item.geo_country].filter(Boolean).join(", ") || "ไม่ทราบตำแหน่ง"}</span>
                        <small className="cx-data">{item.ip || "—"} · {[item.browser, item.os_name].filter(Boolean).join(" / ") || "ไม่ทราบอุปกรณ์"}</small>
                      </td>
                      <td><Risk value={risk} /></td>
                      <td><span className={`cx-chip ${["block", "would_block"].includes(item.decision || "") ? "danger" : ["challenge", "mfa", "would_mfa", "would_challenge"].includes(item.decision || "") ? "warn" : "signal"}`}>{decisionInfo.label}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </>
  );
}

// ── sub-components ──

function Kpi({
  label, value, sub, tone,
}: {
  label: string;
  value: number | string;
  sub: string;
  tone?: "signal" | "danger";
}) {
  return (
    <article className={`cx-kpi ${tone || ""}`}>
      <span className="mono">{label}</span>
      <strong>{value}</strong>
      <small className="mono">{sub}</small>
    </article>
  );
}

function Risk({ value }: { value: number }) {
  const tone = value >= 0.85 ? "crit" : value >= 0.6 ? "high" : value >= 0.3 ? "mid" : "low";
  return (
    <span className="cx-risk">
      <i><span className={tone} style={{ width: `${Math.max(2, Math.round(value * 100))}%` }} /></i>
      <b className="mono">{value.toFixed(2)}</b>
    </span>
  );
}

function EmptyRow({ cols, label }: { cols: number; label: string }) {
  return <tr><td colSpan={cols}><div className="cx-empty"><strong>{label}</strong><span className="mono">NO LIVE DATA</span></div></td></tr>;
}

function SearchIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>;
}

function Select({
  value, onChange, placeholder, children,
}: {
  value: string; onChange: (v: string) => void; placeholder: string; children: React.ReactNode;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="px-3 py-2 rounded-lg border border-ink-200 text-sm bg-white focus:ring-2 focus:ring-brand-500 text-ink-700"
    >
      <option value="">{placeholder}</option>
      {children}
    </select>
  );
}

function chartTitle(hours: number): string {
  if (hours <= 24) return "ปริมาณการเข้าใช้งานรายชั่วโมง";
  if (hours <= 168) return "แนวโน้มการเข้าใช้งานทุก 6 ชั่วโมง";
  return "แนวโน้มการเข้าใช้งานรายวัน";
}

function HourlyChart({
  hourly,
  activities,
  hours,
}: {
  hourly: HourBucket[];
  activities: Activity[];
  hours: number;
}) {
  const bucketHours = hours <= 24 ? 1 : hours <= 168 ? 6 : 24;
  const bucketMs = bucketHours * 60 * 60 * 1000;
  const now = Date.now();
  const rangeStart = now - hours * 60 * 60 * 1000;

  type Point = { total: number; blocked: number };
  const points = new Map<number, Point>();

  const add = (timestamp: number, total: number, blocked: number) => {
    if (!Number.isFinite(timestamp) || timestamp < rangeStart - bucketMs) return;
    const key = Math.floor(timestamp / bucketMs) * bucketMs;
    const current = points.get(key) || { total: 0, blocked: 0 };
    current.total += total;
    current.blocked += blocked;
    points.set(key, current);
  };

  for (const row of hourly) {
    if (!row.hour) continue;
    add(parseUtcTime(row.hour), row.count || 0, row.blocked || 0);
  }

  // รองรับ backend รุ่นเก่าที่ยังไม่ส่ง hourly:
  // สร้างกราฟจาก session จริงที่มากับ response แทน ไม่ใช้ mock data
  if (points.size === 0 && activities.length > 0) {
    for (const activity of activities) {
      if (!activity.created_at) continue;
      const blocked = ["block", "would_block"].includes(activity.decision || "") ? 1 : 0;
      add(parseUtcTime(activity.created_at), 1, blocked);
    }
  }

  const firstBucket = Math.floor(rangeStart / bucketMs) * bucketMs;
  const lastBucket = Math.floor(now / bucketMs) * bucketMs;
  const buckets: number[] = [];
  for (let value = firstBucket; value <= lastBucket; value += bucketMs) buckets.push(value);

  const totalEvents = Array.from(points.values()).reduce((sum, point) => sum + point.total, 0);
  if (totalEvents === 0) {
    return (
      <div className="grid min-h-[132px] place-items-center rounded-lg border border-dashed border-ink-200 bg-ink-50/40 px-4 text-center">
        <div>
          <div className="mx-auto mb-2 h-2 w-2 rounded-full bg-ink-300" />
          <div className="text-sm font-semibold text-ink-500">ยังไม่มีกิจกรรมในช่วงเวลานี้</div>
          <div className="mt-1 font-mono text-[9px] uppercase tracking-wider text-ink-400">
            กราฟจะแสดงเมื่อมี login session
          </div>
        </div>
      </div>
    );
  }

  const labels = buckets.map((timestamp) => formatBucketLabel(timestamp, bucketHours));
  const successful = buckets.map((timestamp) => {
    const point = points.get(timestamp);
    return point ? Math.max(0, point.total - point.blocked) : 0;
  });
  const blocked = buckets.map((timestamp) => points.get(timestamp)?.blocked || 0);

  return (
    <div>
      <LineChart
        labels={labels}
        series={[
          { name: "สำเร็จ", color: "#13b89a", values: successful },
          { name: "ถูกบล็อก", color: "#e11d48", values: blocked },
        ]}
        height={190}
        ticks={4}
        showValues={buckets.length <= 12}
        valueSuffix=" ครั้ง"
        showLegend={false}
      />
    </div>
  );
}

function parseUtcTime(value: string): number {
  const hasTimezone = /[+-]\d{2}:?\d{2}$|Z$/i.test(value);
  return new Date(hasTimezone ? value : value + "Z").getTime();
}

function formatBucketLabel(timestamp: number, bucketHours: number): string {
  const date = new Date(timestamp);
  if (bucketHours >= 24) {
    return date.toLocaleDateString("th-TH", {
      timeZone: "Asia/Bangkok",
      day: "2-digit",
      month: "short",
    });
  }
  if (bucketHours >= 6) {
    return date.toLocaleString("th-TH", {
      timeZone: "Asia/Bangkok",
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      hour12: false,
    });
  }
  return date.toLocaleTimeString("th-TH", {
    timeZone: "Asia/Bangkok",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
