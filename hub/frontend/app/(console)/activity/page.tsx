"use client";

/**
 * Access Activity — realtime login feed (email-centric).
 * แสดง: ใคร · ระบบย่อยไหน · ช่องทาง · ML/risk · decision · ที่ไหน · device · เมื่อไหร่
 * Aesthetic: "Mission Control" — dark control bar + light data board + live pulse.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Topbar } from "@/components/Topbar";
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

  return (
    <>
      <Topbar title="การเข้าใช้งาน (Realtime)" />

      {/* ── Control bar (dark, mission-control) ── */}
      <div className="bg-ink-900 text-ink-100 px-8 py-4">
        <div className="max-w-7xl mx-auto flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2.5 w-2.5">
              {live && (
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              )}
              <span
                className={`relative inline-flex rounded-full h-2.5 w-2.5 ${
                  live ? "bg-emerald-400" : "bg-ink-500"
                }`}
              />
            </span>
            <span className="font-mono text-xs tracking-widest uppercase text-emerald-300">
              {live ? "LIVE" : "PAUSED"}
            </span>
          </div>

          <button
            onClick={() => setLive((v) => !v)}
            className="text-xs px-3 py-1.5 rounded-md border border-ink-700 hover:bg-ink-800 transition"
          >
            {live ? "⏸ หยุด" : "▶ เล่น"}
          </button>

          {/* window selector */}
          <div className="flex items-center gap-1 bg-ink-800 rounded-lg p-1">
            {WINDOWS.map((w) => (
              <button
                key={w.h}
                onClick={() => setHours(w.h)}
                className={`text-xs px-3 py-1 rounded-md transition ${
                  hours === w.h
                    ? "bg-brand-600 text-white font-semibold"
                    : "text-ink-300 hover:text-white"
                }`}
              >
                {w.label}
              </button>
            ))}
          </div>

          <div className="flex-1" />

          {lastUpdated && (
            <span
              className={`font-mono text-[11px] ${
                stale ? "text-amber-400 font-bold" : "text-ink-400"
              }`}
            >
              {stale ? "⚠ ค้าง · " : "อัปเดต "}
              {lastUpdated.toLocaleTimeString("th-TH", { hour12: false })}
            </span>
          )}
          <button
            onClick={() => load(true)}
            className="text-xs px-3 py-1.5 rounded-md bg-ink-800 hover:bg-ink-700 transition"
          >
            ↻ รีเฟรช
          </button>
        </div>
      </div>

      <main className="p-8 max-w-7xl mx-auto w-full">
        {error && (
          <div className="mb-6 p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm">
            {error}
          </div>
        )}

        {/* ── KPI strip ── */}
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-6">
          <Kpi label="Session ใช้งานอยู่" value={data?.active_count ?? "—"} accent="#10b981" sub="Hub + ระบบย่อย" pulse={(data?.active_count ?? 0) > 0} />
          <Kpi label="เข้าใช้งาน" value={k?.total ?? "—"} accent="#0ea5e9" sub={`${hours} ชม.ล่าสุด`} />
          <Kpi label="ถูกบล็อก" value={k?.blocked ?? "—"} accent="#e11d48" sub="block / would-block" danger={(k?.blocked ?? 0) > 0} />
          <Kpi label="ต้อง MFA" value={k?.challenged ?? "—"} accent="#f97316" sub="challenge / mfa" />
          <Kpi
            label="ความเสี่ยงเฉลี่ย"
            value={k?.avg_risk != null ? k.avg_risk.toFixed(2) : "—"}
            accent={k?.avg_risk != null ? riskColor(k.avg_risk) : "#64748b"}
            sub="avg risk score"
          />
        </div>

        {/* ── ผู้ใช้ที่กำลังออนไลน์ (ทุกระบบย่อยรวมกัน) ── */}
        <div
          className={`mb-6 bg-white rounded-xl border shadow-sm overflow-hidden transition ${
            stale ? "border-amber-300 opacity-60 grayscale" : "border-emerald-200"
          }`}
          title={stale ? "ข้อมูลอาจไม่เป็นปัจจุบัน — โหลดรอบล่าสุดไม่สำเร็จ" : undefined}
        >
          <div className="flex items-center gap-2 px-5 py-3 bg-gradient-to-r from-emerald-50 to-white border-b border-emerald-100">
            <span className="relative flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
            </span>
            <h2 className="text-sm font-extrabold text-emerald-900">
              Session ที่ใช้งานอยู่
            </h2>
            <span className="px-2 py-0.5 rounded-full bg-emerald-600 text-white text-xs font-bold tabular-nums">
              {data?.active_count ?? 0}
            </span>
            <span className="hidden md:inline text-[11px] text-emerald-700/70 ml-1">
              🟢 Hub = ออนไลน์จริง · 🔵 ระบบย่อย = session ที่ยัง valid (ค่าประมาณ)
            </span>
          </div>
          {!data ? (
            <div className="px-5 py-8 text-center text-ink-400 text-sm">กำลังโหลด…</div>
          ) : data.active.length === 0 ? (
            <div className="px-5 py-8 text-center text-ink-400 text-sm">
              ไม่มี session ที่ใช้งานอยู่ตอนนี้
            </div>
          ) : (
            <div className="divide-y divide-emerald-50">
              {data.active.map((it) => {
                const ch = channelMeta(it.login_method);
                const risk = it.risk_score ?? it.anomaly_score ?? 0;
                return (
                  <div key={it.id} className="flex items-center gap-3 px-5 py-3 hover:bg-emerald-50/40 transition">
                    <span
                      className="w-9 h-9 rounded-full grid place-items-center text-white text-sm font-bold flex-none ring-2 ring-emerald-200"
                      style={{ background: avatarColor(it.user_email) }}
                    >
                      {(it.full_name || it.user_email || "?")[0]?.toUpperCase()}
                    </span>
                    <div className="min-w-0 w-56">
                      <div className="font-semibold text-ink-900 truncate">{it.user_email || "—"}</div>
                      <div className="text-[11px] text-ink-400 truncate">
                        {it.full_name || ""}{it.user_type ? ` · ${it.user_type}` : ""}
                      </div>
                    </div>
                    <div className="hidden md:block w-44 text-sm text-ink-700 truncate">
                      <span
                        className={`inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle ${
                          it.session_kind === "hub" ? "bg-emerald-500" : "bg-sky-500"
                        }`}
                      />
                      {it.subsystem_name ? `🧩 ${it.subsystem_name}` : "🏛️ Hub-direct"}
                    </div>
                    <span className={`hidden lg:inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[11px] font-semibold ${ch.cls}`}>
                      <span>{ch.icon}</span>{ch.label}
                    </span>
                    <div className="hidden xl:flex items-center gap-1.5 w-24">
                      <div className="flex-1 h-1.5 rounded-full bg-ink-100 overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${Math.round(risk * 100)}%`, background: riskColor(risk) }} />
                      </div>
                      <span className="font-mono text-[10px]" style={{ color: riskColor(risk) }}>{risk.toFixed(2)}</span>
                    </div>
                    <div className="hidden sm:block flex-1 text-xs text-ink-500 truncate text-right">
                      {it.geo_city ? `${it.geo_city}, ` : ""}{it.geo_country || ""}
                      <span className="font-mono text-[10px] text-ink-400 ml-1">{it.ip || ""}</span>
                    </div>
                    <div className="ml-auto sm:ml-0 text-right flex-none w-24">
                      {it.session_kind === "hub" ? (
                        <>
                          <div className="inline-flex items-center gap-1 text-emerald-700 font-bold text-xs">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                            {fmtDuration(it.created_at)}
                          </div>
                          <div className="text-[10px] text-ink-400">ออนไลน์จริง</div>
                        </>
                      ) : (
                        <>
                          <div
                            className="inline-flex items-center gap-1 text-sky-700 font-bold text-xs"
                            title={
                              it.session_expires_at
                                ? `session valid ถึง ${fmtClock(it.session_expires_at)}`
                                : undefined
                            }
                          >
                            <span className="w-1.5 h-1.5 rounded-full bg-sky-500" />
                            {fmtDuration(it.created_at)}
                          </div>
                          <div className="text-[10px] text-ink-400">
                            session{it.session_expires_at ? ` · ถึง ${fmtClock(it.session_expires_at).slice(-8, -3)}` : ""}
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* ── ประวัติการเข้าใช้งาน ── */}
        <div className="flex items-center gap-2 mb-3 mt-2">
          <span className="text-base">📜</span>
          <h2 className="text-sm font-extrabold text-ink-800">ประวัติการเข้าใช้งาน</h2>
          {/* <span className="text-[11px] text-ink-400">(ออกจากระบบแล้ว / หมดอายุ)</span> */}
        </div>

        {/* ── Hourly chart ── */}
        <div className="mb-6 bg-white rounded-xl border border-ink-200 p-5 shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-xs font-bold text-ink-500 uppercase tracking-wider">
              ปริมาณการเข้าใช้งานรายชั่วโมง
            </h2>
            <div className="flex items-center gap-3 text-[11px] text-ink-500">
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-sm bg-brand-500 inline-block" /> สำเร็จ
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-sm bg-rose-500 inline-block" /> ถูกบล็อก
              </span>
            </div>
          </div>
          <HourlyChart hourly={data?.hourly ?? []} />
        </div>

        {/* ── Filters ── */}
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="ค้นหาอีเมล / ชื่อ…"
            className="px-3 py-2 rounded-lg border border-ink-200 text-sm focus:ring-2 focus:ring-brand-500 w-56"
          />
          <Select value={decision} onChange={setDecision} placeholder="ทุก decision">
            {["allow", "warn", "challenge", "mfa", "block", "would_block", "would_mfa"].map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </Select>
          <Select value={channel} onChange={setChannel} placeholder="ทุกช่องทาง">
            {["google", "passkey", "discoverable", "line", "hub_direct"].map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </Select>
          <Select value={subId} onChange={setSubId} placeholder="ทุกระบบ">
            <option value="hub">Hub-direct</option>
            {subsystems.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </Select>
          {(q || decision || channel || subId) && (
            <button
              onClick={() => { setQ(""); setDecision(""); setChannel(""); setSubId(""); }}
              className="text-xs px-3 py-2 rounded-lg border border-ink-200 hover:bg-ink-50 text-ink-600"
            >
              ล้างตัวกรอง
            </button>
          )}
          <span className="ml-auto text-xs text-ink-400">
            แสดง {data?.items.length ?? 0} / {data?.total ?? 0} รายการ
          </span>
        </div>

        {/* ── Feed table ── */}
        <div className="bg-white rounded-xl border border-ink-200 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider bg-ink-50 border-b border-ink-200">
                  <th className="px-4 py-3">ผู้ใช้</th>
                  <th className="px-4 py-3">ระบบ</th>
                  <th className="px-4 py-3">ช่องทาง</th>
                  <th className="px-4 py-3 w-40">ความเสี่ยง (ML)</th>
                  <th className="px-4 py-3">ผล</th>
                  <th className="px-4 py-3">ที่ไหน</th>
                  <th className="px-4 py-3">อุปกรณ์</th>
                  <th className="px-4 py-3 text-right">เมื่อไหร่</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {!data && (
                  <tr><td colSpan={8} className="px-4 py-10 text-center text-ink-400">กำลังโหลด…</td></tr>
                )}
                {data && data.items.length === 0 && (
                  <tr><td colSpan={8} className="px-4 py-10 text-center text-ink-400">ไม่มีการเข้าใช้งานในช่วงนี้</td></tr>
                )}
                {data?.items.map((it) => {
                  const ch = channelMeta(it.login_method);
                  const dec = decisionBadge(it.decision);
                  const risk = it.risk_score ?? it.anomaly_score ?? 0;
                  const fresh = freshIds.has(it.id);
                  return (
                    <tr
                      key={it.id}
                      className={`hover:bg-ink-50/50 transition-colors ${
                        fresh ? "animate-[fadeIn_0.4s_ease] bg-emerald-50/60" : ""
                      }`}
                    >
                      {/* user */}
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2.5">
                          <span
                            className="w-8 h-8 rounded-full grid place-items-center text-white text-xs font-bold flex-none"
                            style={{ background: avatarColor(it.user_email) }}
                          >
                            {(it.full_name || it.user_email || "?")[0]?.toUpperCase()}
                          </span>
                          <div className="min-w-0">
                            <div className="font-semibold text-ink-900 truncate max-w-[180px]">
                              {it.user_email || "—"}
                            </div>
                            <div className="text-[11px] text-ink-400 truncate max-w-[180px]">
                              {it.full_name || ""}{it.user_type ? ` · ${it.user_type}` : ""}
                            </div>
                          </div>
                        </div>
                      </td>
                      {/* subsystem */}
                      <td className="px-4 py-3">
                        {it.subsystem_name ? (
                          <span className="inline-flex items-center gap-1 text-ink-700">
                            🧩 {it.subsystem_name}
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-ink-400 text-xs">
                            🏛️ Hub-direct
                          </span>
                        )}
                      </td>
                      {/* channel */}
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[11px] font-semibold ${ch.cls}`}>
                          <span>{ch.icon}</span>{ch.label}
                        </span>
                      </td>
                      {/* risk meter */}
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="flex-1 h-1.5 rounded-full bg-ink-100 overflow-hidden">
                            <div
                              className="h-full rounded-full transition-all"
                              style={{ width: `${Math.round(risk * 100)}%`, background: riskColor(risk) }}
                            />
                          </div>
                          <span className="font-mono text-[11px] tabular-nums w-8 text-right" style={{ color: riskColor(risk) }}>
                            {risk.toFixed(2)}
                          </span>
                        </div>
                      </td>
                      {/* decision */}
                      <td className="px-4 py-3">
                        <span className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-bold ${dec.cls}`}>
                          {dec.label}
                        </span>
                      </td>
                      {/* where */}
                      <td className="px-4 py-3">
                        <div className="text-ink-700 text-xs">
                          {it.geo_country || it.geo_city ? (
                            <>{it.geo_city ? `${it.geo_city}, ` : ""}{it.geo_country || ""}</>
                          ) : (
                            <span className="text-ink-400">ไม่ทราบ</span>
                          )}
                        </div>
                        <div className="font-mono text-[10px] text-ink-400 flex items-center gap-1">
                          {it.ip || "—"}
                          {it.is_attack_ip && (
                            <span className="px-1 rounded bg-rose-100 text-rose-700 font-bold">⚠ blacklist</span>
                          )}
                        </div>
                      </td>
                      {/* device */}
                      <td className="px-4 py-3">
                        <div className="text-ink-700 text-xs">{it.browser || "—"}</div>
                        <div className="text-[10px] text-ink-400">
                          {it.os_name || ""}{it.device_type ? ` · ${it.device_type}` : ""}
                        </div>
                      </td>
                      {/* when */}
                      <td className="px-4 py-3 text-right whitespace-nowrap">
                        <div className="font-semibold text-ink-700 text-xs">{fmtRel(it.created_at)}</div>
                        <div className="font-mono text-[10px] text-ink-400">{fmtClock(it.created_at)}</div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </main>

      <style jsx>{`
        @keyframes fadeIn {
          from { background-color: rgba(16, 185, 129, 0.25); }
          to { background-color: rgba(16, 185, 129, 0.06); }
        }
      `}</style>
    </>
  );
}

// ── sub-components ──

function Kpi({
  label, value, accent, sub, danger, pulse,
}: {
  label: string; value: number | string; accent: string; sub: string; danger?: boolean; pulse?: boolean;
}) {
  const colored = danger || pulse;
  return (
    <div className="bg-white rounded-xl border border-ink-200 p-4 shadow-sm relative overflow-hidden">
      <div className="absolute left-0 top-0 bottom-0 w-1" style={{ background: accent }} />
      <div className="text-[11px] font-semibold text-ink-500 uppercase tracking-wider flex items-center gap-1.5">
        {pulse && <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: accent }} />}
        {label}
      </div>
      <div
        className={`text-3xl font-extrabold mt-1 tabular-nums ${colored ? "" : "text-ink-900"}`}
        style={colored ? { color: accent } : undefined}
      >
        {value}
      </div>
      <div className="text-[10px] text-ink-400 mt-0.5 font-mono">{sub}</div>
    </div>
  );
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

function HourlyChart({ hourly }: { hourly: HourBucket[] }) {
  if (!hourly.length) {
    return <div className="h-32 grid place-items-center text-ink-300 text-sm">ไม่มีข้อมูล</div>;
  }
  const max = Math.max(...hourly.map((h) => h.count), 1);
  const W = 100;
  const barW = W / hourly.length;
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} 40`} preserveAspectRatio="none" className="w-full h-32">
        {hourly.map((h, i) => {
          const total = (h.count / max) * 38;
          const blocked = (h.blocked / max) * 38;
          const x = i * barW;
          const gap = barW * 0.18;
          return (
            <g key={i}>
              <rect
                x={x + gap}
                y={40 - total}
                width={barW - gap * 2}
                height={total}
                rx={0.4}
                fill="#6366f1"
                opacity={0.85}
              >
                <title>
                  {new Date(
                    (h.hour || "").match(/Z$/) ? h.hour! : h.hour + "Z"
                  ).toLocaleString("th-TH", { timeZone: "Asia/Bangkok", month: "short", day: "2-digit", hour: "2-digit", hour12: false })}
                  {" — "}{h.count} login{h.blocked ? `, ${h.blocked} blocked` : ""}
                </title>
              </rect>
              {blocked > 0 && (
                <rect
                  x={x + gap}
                  y={40 - blocked}
                  width={barW - gap * 2}
                  height={blocked}
                  rx={0.4}
                  fill="#f43f5e"
                />
              )}
            </g>
          );
        })}
      </svg>
      <div className="flex justify-between mt-1 text-[10px] text-ink-400 font-mono">
        <span>
          {hourly[0]?.hour
            ? new Date(hourly[0].hour.match(/Z$/) ? hourly[0].hour : hourly[0].hour + "Z").toLocaleString("th-TH", { timeZone: "Asia/Bangkok", month: "short", day: "2-digit", hour: "2-digit", hour12: false })
            : ""}
        </span>
        <span>
          {hourly[hourly.length - 1]?.hour
            ? new Date((hourly[hourly.length - 1].hour as string).match(/Z$/) ? (hourly[hourly.length - 1].hour as string) : hourly[hourly.length - 1].hour + "Z").toLocaleString("th-TH", { timeZone: "Asia/Bangkok", month: "short", day: "2-digit", hour: "2-digit", hour12: false })
            : ""}
        </span>
      </div>
    </div>
  );
}
