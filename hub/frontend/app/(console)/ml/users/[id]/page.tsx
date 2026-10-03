"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { Badge } from "@/components/Badge";
import { SlidePanel } from "@/components/SlidePanel";
import { clientFetch } from "@/lib/api";
import { AnomalyTable } from "../../_components/AnomalyTable";
import { SessionDetailPanel } from "../../_components/SessionDetailPanel";
import type { UserTimeline, UserSession, BehaviorFrequency } from "../../_types";

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

  return (
    <>
      <Topbar title={`ML Profile · ${displayName}`} />
      <main className="mx-auto w-full max-w-[1480px] p-5 sm:p-6 lg:p-8">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <Link href="/ml" className="inline-flex items-center gap-2 font-mono text-[10px] font-semibold uppercase tracking-[.12em] text-ink-500 hover:text-brand-700">
            <span aria-hidden="true">←</span> ML Overview
          </Link>
          <label className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-ink-500">
            Window
            <select value={days} onChange={(event) => setDays(Number(event.target.value))} className="rounded-lg border border-ink-200 bg-white px-3 py-2 text-xs normal-case text-ink-800">
              <option value={7}>7 วัน</option>
              <option value={30}>30 วัน</option>
              <option value={90}>90 วัน</option>
              <option value={365}>1 ปี</option>
            </select>
          </label>
        </div>

        {error && (
          <div className="mb-5 flex items-center justify-between gap-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            <span>{error}</span>
            <button onClick={load} className="shrink-0 rounded-lg border border-rose-200 bg-white px-3 py-1.5 text-xs font-semibold hover:bg-rose-100">ลองใหม่</button>
          </div>
        )}

        {loading && !data ? <LoadingState /> : data && (
          <>
            <section className="relative overflow-hidden rounded-2xl border border-white/10 bg-ink-900 p-5 text-white sm:p-6">
              <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_92%_5%,rgba(52,232,196,.16),transparent_25rem)]" />
              <div className="relative grid gap-6 xl:grid-cols-[1.2fr_2fr] xl:items-end">
                <div>
                  <div className="flex items-center gap-2 font-mono text-[9px] uppercase tracking-[.2em] text-brand-500"><span className="signal-dot" /> Individual risk baseline</div>
                  <h2 className="mt-4 font-display text-2xl font-extrabold sm:text-3xl">{displayName}</h2>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs text-ink-400">{data.user.email}</span>
                    <Badge tone={USER_TYPE_TONE[data.user.user_type] || "default"}>{data.user.user_type}</Badge>
                    <span className="rounded-full border border-white/10 px-2.5 py-1 font-mono text-[9px] text-ink-400">ID {data.user.id}</span>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-white/10 bg-white/10 sm:grid-cols-4">
                  <DarkMetric label="Sessions" value={String(sessions.length)} sub={`${days} วันล่าสุด`} />
                  <DarkMetric label="Avg risk" value={summary.average.toFixed(3)} sub="ค่าเฉลี่ย anomaly score" tone={riskTone(summary.average)} />
                  <DarkMetric label="Flagged" value={String(summary.flagged)} sub="score >= 0.4" tone={summary.flagged ? "text-amber-300" : "text-brand-500"} />
                  <DarkMetric label="Peak risk" value={summary.peak.toFixed(3)} sub="สูงสุดในช่วงนี้" tone={riskTone(summary.peak)} />
                </div>
              </div>
            </section>

            <div className="mt-5 space-y-5">
              <section className="rounded-xl border border-ink-200 bg-white p-5">
                <SectionTitle eyebrow="Risk timeline" title="รูปแบบความเสี่ยงตามเวลา" detail={`${days} วันล่าสุด · ${sessions.length} sessions`} />
                <RiskSparkline sessions={sessions} />
              </section>

              <section className="overflow-hidden rounded-2xl border border-ink-200 bg-white shadow-[0_12px_36px_rgba(15,23,42,.04)]">
                <div className="flex flex-wrap items-start justify-between gap-4 border-b border-ink-100 px-5 py-5 sm:px-6">
                  <SectionTitle eyebrow="Behavior baseline" title="ข้อมูลพฤติกรรมที่ใช้ประเมิน" detail="ภาพรวม ณ ตอนนี้ · เวลาไทย" />
                  <span className="rounded-lg border border-ink-200 bg-ink-50 px-3 py-2 font-mono text-[10px] font-semibold text-ink-600">ย้อนหลัง {data.behavior_baseline?.days ?? days} วัน</span>
                </div>
                {data.behavior_baseline ? (
                  <div className="p-5 sm:p-6">
                    <p className="mb-4 text-xs text-ink-500">
                      {data.behavior_baseline.session_count} ครั้ง · {data.behavior_baseline.ready ? "พร้อมใช้เป็นพฤติกรรม" : `ข้อมูลยังไม่พอ (ต้องมี ${data.behavior_baseline.min_sessions} ครั้ง)`}
                    </p>

                    <div className="grid gap-3 sm:grid-cols-3">
                      <BaselineSummary label="การเข้าใช้งาน" value={`${data.behavior_baseline.session_count}`} unit="ครั้ง" />
                      <BaselineSummary label="อุปกรณ์หลัก" value={data.behavior_baseline.devices[0]?.value || "ยังไม่มีข้อมูล"} />
                      <BaselineSummary label="ช่วงวันที่ใช้งาน" value={data.behavior_baseline.typical_weekend === null ? "ข้อมูลยังไม่พอ" : data.behavior_baseline.typical_weekend ? "เสาร์–อาทิตย์" : "จันทร์–ศุกร์"} />
                    </div>

                    <div className="mt-4 grid items-stretch gap-4 xl:grid-cols-12">
                      <div className="rounded-xl border border-ink-200 p-5 xl:col-span-5">
                        <FrequencyBars label="ช่วงเวลาที่ใช้บ่อย" items={data.behavior_baseline.hours} />
                        <div className="mt-5 rounded-xl bg-brand-50 px-4 py-3">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="text-xs font-semibold text-ink-700">เวลาอ้างอิง</span>
                            <span className="font-mono text-sm font-semibold text-ink-900">
                              {data.behavior_baseline.temporal_median_hour === null ? "ข้อมูลยังไม่พอ" : `${data.behavior_baseline.temporal_median_hour} น.`}
                            </span>
                          </div>
                          <p className="mt-1 text-[11px] leading-relaxed text-ink-500">
                            มัธยฐานจาก {data.behavior_baseline.temporal_count} ครั้งล่าสุด (สูงสุด 50) · ใช้คำนวณ hours_diff
                          </p>
                        </div>
                      </div>

                      <div className="rounded-xl border border-ink-200 p-5 xl:col-span-7">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div>
                            <h4 className="text-sm font-semibold text-ink-800">อุปกรณ์ที่ใช้ประจำ</h4>
                            <p className="mt-1 text-[11px] text-ink-500">OS + ประเภทอุปกรณ์ + ตระกูลเบราว์เซอร์</p>
                          </div>
                          <span className="text-[10px] text-ink-400">ไม่รวมเลขเวอร์ชันเบราว์เซอร์</span>
                        </div>
                        <DeviceSignatureTable items={data.behavior_baseline.device_signatures} />
                      </div>
                    </div>

                    <div className="mt-4 grid gap-4 lg:grid-cols-3">
                      <FrequencyBars label="เบราว์เซอร์" items={data.behavior_baseline.browsers} compact />
                      <FrequencyBars label="ระบบปฏิบัติการ (OS)" items={data.behavior_baseline.operating_systems} compact />
                      <div className="rounded-xl border border-ink-200 p-5">
                        <FrequencyBars label="ประเภทอุปกรณ์" items={data.behavior_baseline.devices} compact embedded />
                        <div className="mt-4 border-t border-ink-100 pt-4">
                          <h4 className="text-xs font-semibold text-ink-700">ประเทศ</h4>
                          <p className="mt-2 text-xs text-ink-500">
                            {data.behavior_baseline.countries.length ? data.behavior_baseline.countries.map((item) => `${item.value} · ${item.count} ครั้ง`).join(" / ") : "ยังไม่มีข้อมูลที่ระบุ"}
                          </p>
                        </div>
                      </div>
                    </div>

                    <div className="mt-4 grid gap-4 lg:grid-cols-2">
                      <FrequencyBars label="ระบบที่เข้าบ่อย" detail="ใช้เทียบระบบใหม่ ระบบที่ใช้นาน ๆ ครั้ง และระดับสิทธิ์" items={data.behavior_baseline.subsystems} compact />
                      <FrequencyBars label="IP ที่พบในประวัติ" detail="ข้อมูลประกอบ · ชั้น 2 ไม่ให้คะแนนจากความถี่ IP โดยตรง" items={data.behavior_baseline.ips} compact />
                    </div>

                    <p className="mt-4 border-t border-ink-100 pt-4 text-[11px] text-ink-400">
                      ข้อมูลสรุปปัจจุบัน ไม่ใช่ baseline ย้อนหลังของแต่ละเหตุการณ์
                    </p>
                  </div>
                ) : <p className="px-6 py-8 text-sm text-ink-500">ยังไม่มีข้อมูล baseline จากเซิร์ฟเวอร์</p>}
              </section>
            </div>

            <section className="mt-5 rounded-xl border border-ink-200 bg-white p-5">
              <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
                <SectionTitle eyebrow="Session evidence" title="ประวัติการประเมินทั้งหมด" detail="เลือกแถวเพื่อดู 4-layer breakdown และบันทึก feedback" />
                <div className="flex flex-wrap gap-2">
                  {Object.entries(summary.decisions).map(([decision, count]) => (
                    <span key={decision} className="rounded-full border border-ink-200 bg-ink-50 px-2.5 py-1 font-mono text-[9px] uppercase text-ink-600">{decision} {count}</span>
                  ))}
                </div>
              </div>
              <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-[.12em] text-ink-500">Sessions · {sessions.length} รายการ</h3>
              <AnomalyTable rows={sessions} onRowClick={setSelected} showUser={false} showFeedback emptyMessage="ไม่มี session ในช่วงเวลานี้" />
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

function SectionTitle({ eyebrow, title, detail }: { eyebrow: string; title: string; detail?: string }) {
  return <div><div className="font-mono text-[9px] font-semibold uppercase tracking-[.18em] text-ink-400">{eyebrow}</div><h3 className="mt-1 font-display text-lg font-bold text-ink-900">{title}</h3>{detail && <p className="mt-1 text-xs text-ink-500">{detail}</p>}</div>;
}

function DarkMetric({ label, value, sub, tone = "text-white" }: { label: string; value: string; sub?: string; tone?: string }) {
  return <div className="bg-ink-800/75 px-4 py-4"><dt className="font-mono text-[8px] uppercase tracking-[.16em] text-ink-500">{label}</dt><dd className={`mt-2 font-display text-2xl font-extrabold tabular-nums ${tone}`}>{value}</dd>{sub && <dd className="mt-1 text-[10px] leading-snug text-ink-400">{sub}</dd>}</div>;
}

function BaselineRow({ label, value }: { label: string; value: string }) {
  return <div className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0"><dt className="text-xs text-ink-500">{label}</dt><dd className="text-right font-mono text-[11px] font-semibold text-ink-800">{value}</dd></div>;
}

function BaselineSummary({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return <div className="rounded-xl border border-ink-200 bg-ink-50/40 px-5 py-4">
    <dt className="text-xs font-semibold text-ink-500">{label}</dt>
    <dd className="mt-2 flex items-baseline gap-2 font-display text-2xl font-extrabold text-ink-900">
      <span className="truncate">{value}</span>{unit && <span className="text-xs font-medium text-ink-500">{unit}</span>}
    </dd>
  </div>;
}

function FrequencyBars({ label, detail, items, compact = false, embedded = false }: { label: string; detail?: string; items: BehaviorFrequency[]; compact?: boolean; embedded?: boolean }) {
  const max = Math.max(1, ...items.map((item) => item.count));
  return <div className={embedded ? "min-w-0" : "min-w-0 rounded-xl border border-ink-200 p-5"}>
    <h4 className="text-xs font-semibold text-ink-700">{label}</h4>
    {detail && <p className="mt-1 text-[11px] leading-relaxed text-ink-500">{detail}</p>}
    {items.length ? <ul className={`mt-3 ${compact ? "space-y-3" : "space-y-3.5"}`}>
      {items.map((item) => <li key={item.value} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1">
        <span className="truncate text-xs text-ink-800" title={item.value}>{item.value}</span>
        <span className="font-mono text-[11px] tabular-nums text-ink-500">{item.count} ครั้ง</span>
        <span className="col-span-2 h-1.5 overflow-hidden rounded-full bg-ink-100">
          <span className="block h-full rounded-full bg-brand-600" style={{ width: `${Math.max(3, item.count / max * 100)}%` }} />
        </span>
      </li>)}
    </ul> : <p className="mt-3 text-xs text-ink-400">ไม่มีข้อมูลที่ระบุ</p>}
  </div>;
}

function DeviceSignatureTable({ items }: { items: BehaviorFrequency[] }) {
  if (!items.length) return <p className="mt-4 text-xs text-ink-400">ไม่มีข้อมูลที่ระบุ</p>;
  return <div className="mt-4 overflow-x-auto">
    <table className="w-full min-w-[520px] text-left text-xs">
      <thead><tr className="border-b border-ink-200 bg-ink-50 text-ink-500">
        <th className="px-3 py-2.5 font-semibold">ระบบปฏิบัติการ</th>
        <th className="px-3 py-2.5 font-semibold">อุปกรณ์</th>
        <th className="px-3 py-2.5 font-semibold">เบราว์เซอร์</th>
        <th className="px-3 py-2.5 text-right font-semibold">จำนวน</th>
      </tr></thead>
      <tbody className="divide-y divide-ink-100">
        {items.map((item) => {
          const [os = "—", device = "—", browser = "—"] = item.value.split(" · ");
          return <tr key={item.value}>
            <td className="px-3 py-3 text-ink-800">{os}</td>
            <td className="px-3 py-3 text-ink-700">{device}</td>
            <td className="px-3 py-3 text-ink-700">{browser}</td>
            <td className="px-3 py-3 text-right font-mono tabular-nums text-ink-500">{item.count} ครั้ง</td>
          </tr>;
        })}
      </tbody>
    </table>
  </div>;
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
  return <div className="space-y-5" aria-label="กำลังโหลด"><div className="h-48 animate-pulse rounded-2xl bg-ink-200" /><div className="space-y-5"><div className="h-64 animate-pulse rounded-xl bg-white" /><div className="h-64 animate-pulse rounded-xl bg-white" /></div></div>;
}

function summarize(sessions: UserSession[]) {
  const scores = sessions.map((session) => session.risk_score ?? session.score ?? 0);
  const average = scores.length ? scores.reduce((sum, score) => sum + score, 0) / scores.length : 0;
  const decisions = countBy(sessions.map((session) => session.decision || "unknown"));
  const hourCounts: Record<number, number> = {};
  const hourFormatter = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Bangkok", hour: "2-digit", hourCycle: "h23",
  });
  for (const session of sessions) {
    const date = new Date(asUtc(session.created_at));
    if (!Number.isFinite(date.getTime())) continue;
    const hour = Number(hourFormatter.format(date));
    hourCounts[hour] = (hourCounts[hour] || 0) + 1;
  }
  const frequentHours = Object.entries(hourCounts)
    .sort((a, b) => b[1] - a[1] || Number(a[0]) - Number(b[0]));
  const validCount = frequentHours.reduce((sum, [, count]) => sum + count, 0);
  const hourRange = frequentHours.slice(0, 3).map(([hour, count]) => {
    const label = String(hour).padStart(2, "0");
    return `${label}:00–${label}:59 น. · ${count} ครั้ง (${Math.round(count / validCount * 100)}%)`;
  }).join(" / ") || "—";
  return {
    average,
    peak: scores.length ? Math.max(...scores) : 0,
    flagged: scores.filter((score) => score >= .4).length,
    country: topValue(sessions.map((session) => session.geo_country || "ไม่ระบุ")),
    device: topValue(sessions.map((session) => [session.device_type, session.browser].filter(Boolean).join(" · ") || "ไม่ระบุ")),
    decision: topValue(sessions.map((session) => session.decision || "unknown")).toUpperCase(),
    hourRange,
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

function FrequencyGroup({ label, detail, items, embedded = false }: { label: string; detail?: string; items: BehaviorFrequency[]; embedded?: boolean }) {
  return <div className={embedded ? "min-w-0" : "min-w-0 rounded-lg border border-ink-200 bg-ink-50/40 p-4"}>
    <h4 className="text-xs font-semibold text-ink-700">{label}</h4>
    {detail && <p className="mt-1 text-xs text-ink-500">{detail}</p>}
    {items.length ? <ul className="mt-2 space-y-2">{items.map(item => <li key={item.value} className="flex items-start justify-between gap-3 text-xs"><span className="min-w-0 break-words text-ink-800">{item.value}</span><span className="shrink-0 text-ink-500">{item.count} ครั้ง</span></li>)}</ul> : <p className="mt-2 text-xs text-ink-400">ไม่มีข้อมูลที่ระบุ</p>}
  </div>;
}
