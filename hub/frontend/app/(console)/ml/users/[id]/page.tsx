"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { SlidePanel } from "@/components/SlidePanel";
import { clientFetch } from "@/lib/api";
import { SessionDetailPanel } from "../../_components/SessionDetailPanel";
import type { UserTimeline, UserSession } from "../../_types";

const USER_TYPE_TONE: Record<string, "good" | "warn" | "danger" | "brand" | "default"> = {
  admin: "danger",
  staff: "brand",
  teacher: "warn",
  student: "good",
};

export default function UserTimelinePage({ params }: { params: { id: string } }) {
  const userId = params.id;
  const [data, setData] = useState<UserTimeline["data"] | null>(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<UserSession | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    clientFetch<UserTimeline>(
      `/admin/ml/users/${encodeURIComponent(userId)}/sessions?days=${days}&limit=100`
    )
      .then((response) => setData(response.data))
      .catch((reason) => setError(reason.detail || "โหลดข้อมูลผู้ใช้ไม่สำเร็จ"))
      .finally(() => setLoading(false));
  }, [userId, days]);

  useEffect(load, [load]);

  const sessions = useMemo(() => data?.sessions ?? [], [data]);
  const summary = useMemo(() => summarize(sessions), [sessions]);
  const displayName = data?.user.full_name || data?.user.email || "User ML Profile";

  const actions = (
    <div className="cx-command-actions">
      <Link className="cx-ml-threshold-link" href="/ml">← ML Overview</Link>
      <select className="cx-command-select" value={days} onChange={(event) => setDays(Number(event.target.value))}>
        <option value={7}>7 วัน</option><option value={30}>30 วัน</option><option value={90}>90 วัน</option><option value={365}>1 ปี</option>
      </select>
    </div>
  );

  return (
    <>
      <Topbar title={`ML Profile · ${displayName}`} actions={actions} />
      <main className="cx-document">
        {error && <div className="cx-alert danger"><span>{error}</span><button type="button" onClick={load}>ลองใหม่</button></div>}
        {loading && !data ? <LoadingState /> : data && (
          <>
            <section className="cx-identity-hero">
              <div>
                <span className="mono">BEHAVIOR PROFILE</span>
                <h2>{displayName} <small>{data.user.user_type}</small></h2>
                <code className="mono">{data.user.email} · {data.user.id}</code>
              </div>
              <div className="cx-hero-metrics">
                <span>SESSIONS<b className="mono">{sessions.length}</b></span>
                <span>AVG RISK<b className="mono">{summary.average.toFixed(3)}</b></span>
                <span>FLAGGED<b className="mono">{summary.flagged}</b></span>
                <span>PEAK RISK<b className="mono">{summary.peak.toFixed(3)}</b></span>
              </div>
            </section>

            <section className="cx-grid two">
              <article className="cx-panel">
                <header><div><span className="mono">RISK TIMELINE · {days} DAYS</span><h2>รูปแบบความเสี่ยงตามเวลา</h2></div></header>
                <div className="cx-profile-chart"><RiskSparkline sessions={sessions} /></div>
              </article>
              <article className="cx-panel">
                <header><div><span className="mono">BEHAVIOR BASELINE</span><h2>พฤติกรรมปกติของผู้ใช้</h2></div></header>
                <div className="cx-definition">
                  <div><span>ประเทศที่พบบ่อย</span><b>{summary.country}</b></div>
                  <div><span>อุปกรณ์ที่พบบ่อย</span><b>{summary.device}</b></div>
                  <div><span>ช่วงเวลาที่ใช้บ่อย</span><b className="mono">{summary.hourRange}</b></div>
                  <div><span>Decision หลัก</span><b className="mono">{summary.decision}</b></div>
                </div>
              </article>
            </section>

            <section className="cx-panel">
              <header><div><span className="mono">SESSION EVIDENCE · {sessions.length} RECORDS</span><h2>ประวัติการประเมินทั้งหมด</h2></div><span className="cx-chip outline">เลือกแถวเพื่อดู 4-Layer</span></header>
              <div className="cx-table-wrap">
                <table>
                  <thead><tr><th>TIME</th><th>RISK SCORE</th><th>DECISION</th><th>DEVICE</th><th>IP / COUNTRY</th><th>FEEDBACK</th></tr></thead>
                  <tbody>
                    {sessions.length === 0 && <tr><td colSpan={6}><div className="cx-empty"><strong>ไม่มี Session ในช่วงเวลานี้</strong><span className="mono">NO USER RISK HISTORY</span></div></td></tr>}
                    {sessions.map((session) => {
                      const risk = session.risk_score ?? session.score ?? 0;
                      return <tr key={session.id} className="cx-clickable-row" onClick={() => setSelected(session)}>
                        <td><code>{new Date(asUtc(session.created_at)).toLocaleString("th-TH", { timeZone: "Asia/Bangkok" })}</code></td>
                        <td><Risk value={risk} /></td>
                        <td><span className={`cx-chip ${decisionTone(session.decision)}`}>{(session.decision || "UNKNOWN").toUpperCase()}</span></td>
                        <td><span>{[session.device_type, session.browser].filter(Boolean).join(" · ") || "—"}</span><small className="cx-data">{session.os_name || "UNKNOWN OS"}</small></td>
                        <td><code>{session.ip || "—"}</code><small className="cx-data">{[session.geo_city, session.geo_country].filter(Boolean).join(", ") || "ไม่ทราบตำแหน่ง"}</small></td>
                        <td><span className="cx-chip outline">{session.feedback_label || "ยังไม่ตรวจ"}</span></td>
                      </tr>;
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )}
      </main>

      <SlidePanel open={!!selected} onClose={() => setSelected(null)} title="Session Detail">
        {selected && <SessionDetailPanel session={selected} onFeedbackSaved={() => { load(); setSelected(null); }} hideUserLink />}
      </SlidePanel>
    </>
  );

}

function Risk({ value }: { value: number }) {
  const tone = value >= .85 ? "crit" : value >= .6 ? "high" : value >= .3 ? "mid" : "low";
  return <span className="cx-risk"><i><span className={tone} style={{ width: `${Math.max(2, Math.round(value * 100))}%` }} /></i><b className="mono">{value.toFixed(3)}</b></span>;
}

function decisionTone(value: string | null) {
  if (["block", "would_block"].includes(value || "")) return "danger";
  if (["mfa", "challenge", "would_mfa", "would_challenge", "warn"].includes(value || "")) return "warn";
  return "signal";
}

function SectionTitle({ eyebrow, title, detail }: { eyebrow: string; title: string; detail?: string }) {
  return <div><div className="font-mono text-[9px] font-semibold uppercase tracking-[.18em] text-ink-400">{eyebrow}</div><h3 className="mt-1 font-display text-lg font-bold text-ink-900">{title}</h3>{detail && <p className="mt-1 text-xs text-ink-500">{detail}</p>}</div>;
}

function DarkMetric({ label, value, sub, tone = "text-white" }: { label: string; value: string; sub?: string; tone?: string }) {
  return <div className="bg-ink-800/75 px-4 py-4"><dt className="font-mono text-[8px] uppercase tracking-[.16em] text-ink-500">{label}</dt><dd className={`mt-2 font-display text-2xl font-extrabold tabular-nums ${tone}`}>{value}</dd>{sub && <dd className="mt-1 text-[10px] leading-snug text-ink-400">{sub}</dd>}</div>;
}

function BaselineRow({ label, value }: { label: string; value: string }) {
  return <div className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0"><dt className="text-xs text-ink-500">{label}</dt><dd className="text-right font-mono text-[11px] font-semibold text-ink-800">{value}</dd></div>;
}

function RiskSparkline({ sessions }: { sessions: UserSession[] }) {
  const values = [...sessions].sort((a, b) => Date.parse(asUtc(a.created_at)) - Date.parse(asUtc(b.created_at))).map((session) => session.risk_score ?? session.score ?? 0);
  if (!values.length) return <div className="mt-5 grid h-44 place-items-center rounded-lg border border-dashed border-ink-200 text-sm text-ink-400">ยังไม่มีข้อมูลความเสี่ยง</div>;
  const width = 800;
  const height = 190;
  const inset = 16;
  const points = values.map((value, index) => {
    const x = inset + (index / Math.max(values.length - 1, 1)) * (width - inset * 2);
    const y = height - inset - Math.min(Math.max(value, 0), 1) * (height - inset * 2);
    return `${x},${y}`;
  }).join(" ");
  return (
    <div className="mt-4">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-48 w-full" role="img" aria-label="กราฟคะแนนความเสี่ยงตามเวลา">
        {[0.25, 0.5, 0.75].map((level) => <line key={level} x1={inset} x2={width - inset} y1={height - inset - level * (height - inset * 2)} y2={height - inset - level * (height - inset * 2)} stroke="#e5e9ef" strokeDasharray="4 6" />)}
        <defs><linearGradient id="riskLine" x1="0" x2="1"><stop offset="0" stopColor="#10b981" /><stop offset=".55" stopColor="#f59e0b" /><stop offset="1" stopColor="#e11d48" /></linearGradient></defs>
        <polyline points={points} fill="none" stroke="url(#riskLine)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div className="flex justify-between font-mono text-[9px] uppercase tracking-wider text-ink-400"><span>Older</span><span>Latest</span></div>
    </div>
  );
}

function LoadingState() {
  return <div className="space-y-5" aria-label="กำลังโหลด"><div className="h-48 animate-pulse rounded-2xl bg-ink-200" /><div className="grid gap-5 xl:grid-cols-[1.7fr_1fr]"><div className="h-64 animate-pulse rounded-xl bg-white" /><div className="h-64 animate-pulse rounded-xl bg-white" /></div></div>;
}

function summarize(sessions: UserSession[]) {
  const scores = sessions.map((session) => session.risk_score ?? session.score ?? 0);
  const average = scores.length ? scores.reduce((sum, score) => sum + score, 0) / scores.length : 0;
  const decisions = countBy(sessions.map((session) => session.decision || "unknown"));
  const hours = sessions.map((session) => Number(new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Bangkok",
    hour: "2-digit",
    hour12: false,
  }).format(new Date(asUtc(session.created_at)))));
  const minHour = hours.length ? Math.min(...hours) : 0;
  const maxHour = hours.length ? Math.max(...hours) : 0;
  return {
    average,
    peak: scores.length ? Math.max(...scores) : 0,
    flagged: scores.filter((score) => score >= .4).length,
    country: topValue(sessions.map((session) => session.geo_country || "ไม่ระบุ")),
    device: topValue(sessions.map((session) => [session.device_type, session.browser].filter(Boolean).join(" · ") || "ไม่ระบุ")),
    decision: topValue(sessions.map((session) => session.decision || "unknown")).toUpperCase(),
    hourRange: hours.length ? `${String(minHour).padStart(2, "0")}:00–${String(maxHour).padStart(2, "0")}:59 น.` : "—",
    decisions,
  };
}

function countBy(values: string[]) {
  return values.reduce<Record<string, number>>((result, value) => { result[value] = (result[value] || 0) + 1; return result; }, {});
}

function topValue(values: string[]) {
  const counts = countBy(values);
  return Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] || "—";
}

function riskTone(score: number) {
  return score >= .85 ? "text-rose-400" : score >= .6 ? "text-orange-300" : score >= .3 ? "text-amber-300" : "text-brand-500";
}

function asUtc(value: string) {
  return /[+-]\d{2}:?\d{2}$|Z$/i.test(value) ? value : `${value}Z`;
}
