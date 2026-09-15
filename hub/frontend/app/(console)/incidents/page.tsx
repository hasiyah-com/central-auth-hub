// "use client";

// /**
//  * Incidents — triage list ของ login ที่ RBA flag ว่าเสี่ยง.
//  * คลิกแถว → drawer แสดง Incident Summary (Entry→Detected→Impact→Actions).
//  */

// import { useCallback, useEffect, useState } from "react";
// import { Topbar } from "@/components/Topbar";
// import { Badge } from "@/components/Badge";
// import { StatsCard } from "@/components/StatsCard";
// import { clientFetch } from "@/lib/api";
// import { IncidentDetailModal } from "./_components/IncidentDetailModal";
// import {
//   type IncidentListResponse,
//   type IncidentDetail,
//   type IncidentRow,
//   DECISION_TONE,
//   STATUS_META,
// } from "./_types";

// const WINDOW_OPTIONS = [
//   { v: 24, label: "24 ชม." },
//   { v: 168, label: "7 วัน" },
//   { v: 720, label: "30 วัน" },
// ];

// export default function IncidentsPage() {
//   const [data, setData] = useState<IncidentListResponse | null>(null);
//   const [loading, setLoading] = useState(true);
//   const [error, setError] = useState<string | null>(null);
//   const [hours, setHours] = useState(168);
//   const [decision, setDecision] = useState("");
//   const [q, setQ] = useState("");

//   // drawer
//   const [detail, setDetail] = useState<IncidentDetail | null>(null);
//   const [detailLoading, setDetailLoading] = useState(false);
//   const [openId, setOpenId] = useState<string | null>(null);

//   const load = useCallback(() => {
//     setLoading(true);
//     setError(null);
//     const qs = new URLSearchParams({ hours: String(hours), limit: "100" });
//     if (decision) qs.set("decision", decision);
//     if (q.trim()) qs.set("q", q.trim());
//     clientFetch<IncidentListResponse>(`/admin/incidents?${qs.toString()}`)
//       .then(setData)
//       .catch((e) => setError(e?.detail || "โหลดไม่สำเร็จ"))
//       .finally(() => setLoading(false));
//   }, [hours, decision, q]);

//   // eslint-disable-next-line react-hooks/exhaustive-deps
//   useEffect(load, [hours, decision]);

//   const fetchDetail = useCallback((id: string) => {
//     setDetailLoading(true);
//     clientFetch<IncidentDetail>(`/admin/incidents/${id}`)
//       .then(setDetail)
//       .catch(() => setDetail(null))
//       .finally(() => setDetailLoading(false));
//   }, []);

//   function openDetail(row: IncidentRow) {
//     setOpenId(row.id);
//     setDetail(null);
//     fetchDetail(row.id);
//   }

//   const kpis = data?.kpis;

//   return (
//     <>
//       <Topbar title="Incidents" />
//       <main className="p-8 max-w-7xl mx-auto w-full">
//         {/* KPIs */}
//         <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
//           <StatsCard label="เหตุการณ์ทั้งหมด" value={kpis?.total ?? "—"} />
//           <StatsCard label="ถูกบล็อก" value={kpis?.blocked ?? "—"} />
//           <StatsCard label="ต้องยืนยันตัวตน" value={kpis?.challenged ?? "—"} />
//           <StatsCard label="Attack IP" value={kpis?.attack_ip ?? "—"} />
//         </div>

//         {/* filters */}
//         <div className="mb-4 flex flex-wrap items-center gap-3">
//           <div className="flex rounded-lg border border-ink-200 overflow-hidden">
//             {WINDOW_OPTIONS.map((o) => (
//               <button
//                 key={o.v}
//                 onClick={() => setHours(o.v)}
//                 className={
//                   "px-3 py-1.5 text-sm font-medium transition " +
//                   (hours === o.v
//                     ? "bg-brand-600 text-white"
//                     : "bg-white text-ink-600 hover:bg-ink-50")
//                 }
//               >
//                 {o.label}
//               </button>
//             ))}
//           </div>
//           <select
//             value={decision}
//             onChange={(e) => setDecision(e.target.value)}
//             className="px-3 py-2 rounded-lg border border-ink-200 bg-white text-sm focus:outline-none focus:border-brand-500"
//           >
//             <option value="">ทุก decision</option>
//             <option value="block">block</option>
//             <option value="would_block">would_block</option>
//             <option value="challenge">challenge</option>
//             <option value="would_mfa">would_mfa</option>
//             <option value="mfa_passed">mfa_passed</option>
//           </select>
//           <input
//             type="text"
//             value={q}
//             onChange={(e) => setQ(e.target.value)}
//             onKeyDown={(e) => e.key === "Enter" && load()}
//             placeholder="ค้นหา email / ชื่อ… (Enter)"
//             className="px-3 py-2 rounded-lg border border-ink-200 bg-white text-sm focus:outline-none focus:border-brand-500 w-60"
//           />
//         </div>

//         {error && (
//           <div className="mb-4 p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm">
//             {error}
//           </div>
//         )}

//         {/* list */}
//         <div className="bg-white rounded-xl border border-ink-200 overflow-hidden">
//           <table className="w-full text-sm">
//             <thead>
//               <tr className="text-left text-[11px] font-bold text-ink-400 uppercase tracking-wider border-b border-ink-100">
//                 <th className="px-4 py-3">เวลา</th>
//                 <th className="px-4 py-3">ผู้ใช้</th>
//                 <th className="px-4 py-3">เข้าทาง → เป้าหมาย</th>
//                 <th className="px-4 py-3">Risk</th>
//                 <th className="px-4 py-3">Decision</th>
//                 <th className="px-4 py-3">สถานะ</th>
//               </tr>
//             </thead>
//             <tbody>
//               {loading ? (
//                 <tr>
//                   <td colSpan={6} className="px-4 py-10 text-center text-ink-400">
//                     กำลังโหลด…
//                   </td>
//                 </tr>
//               ) : !data || data.items.length === 0 ? (
//                 <tr>
//                   <td colSpan={6} className="px-4 py-10 text-center text-ink-400">
//                     ไม่มีเหตุการณ์เสี่ยงในช่วงที่เลือก
//                   </td>
//                 </tr>
//               ) : (
//                 data.items.map((row) => {
//                   const status = STATUS_META[row.status] ?? STATUS_META.expired;
//                   return (
//                     <tr
//                       key={row.id}
//                       onClick={() => openDetail(row)}
//                       className={
//                         "border-b border-ink-50 hover:bg-brand-50/40 cursor-pointer transition " +
//                         (openId === row.id ? "bg-brand-50" : "")
//                       }
//                     >
//                       <td className="px-4 py-3 font-mono text-xs text-ink-500 whitespace-nowrap">
//                         {row.created_at
//                           ? new Date(row.created_at)
//                               .toISOString()
//                               .slice(5, 16)
//                               .replace("T", " ")
//                           : "—"}
//                       </td>
//                       <td className="px-4 py-3">
//                         <div className="font-medium text-ink-900 truncate max-w-[160px]">
//                           {row.full_name || row.user_email || "—"}
//                         </div>
//                         <div className="text-[11px] text-ink-400 font-mono truncate max-w-[160px]">
//                           {row.user_email}
//                         </div>
//                       </td>
//                       <td className="px-4 py-3">
//                         <div className="text-ink-800">{row.channel_label}</div>
//                         <div className="text-[11px] text-ink-400">
//                           {row.is_subsystem ? "" : ""}
//                           {row.target}
//                         </div>
//                       </td>
//                       <td className="px-4 py-3 font-mono font-bold tabular-nums">
//                         {row.risk_score != null ? row.risk_score.toFixed(2) : "—"}
//                       </td>
//                       <td className="px-4 py-3">
//                         <Badge tone={DECISION_TONE[row.decision || ""] || "default"}>
//                           {row.decision || "—"}
//                         </Badge>
//                       </td>
//                       <td className="px-4 py-3">
//                         <Badge tone={status.tone}>{status.label}</Badge>
//                       </td>
//                     </tr>
//                   );
//                 })
//               )}
//             </tbody>
//           </table>
//         </div>

//         {data && data.total > data.items.length && (
//           <p className="mt-3 text-xs text-ink-400 text-center">
//             แสดง {data.items.length} จาก {data.total} เหตุการณ์ — กรอง/ลดช่วงเวลาเพื่อดูเจาะจง
//           </p>
//         )}
//       </main>

//       {/* full-screen detail modal */}
//       {openId !== null && !detailLoading && detail && (
//         <IncidentDetailModal
//           data={detail}
//           onClose={() => setOpenId(null)}
//           onActionDone={() => {
//             if (openId) fetchDetail(openId);
//             load();
//           }}
//         />
//       )}
//       {openId !== null && detailLoading && (
//         <div className="fixed inset-0 z-50 bg-ink-900/50 grid place-items-center">
//           <div className="bg-white rounded-2xl px-6 py-5 shadow-xl text-sm text-ink-500">
//             กำลังโหลด…
//           </div>
//         </div>
//       )}
//     </>
//   );
// }


"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";
import { parseUTC } from "@/lib/format";
import { IncidentDetailModal } from "./_components/IncidentDetailModal";
import { type IncidentDetail, type IncidentListResponse, type IncidentRow, STATUS_META } from "./_types";
import styles from "./incidents.module.css";

type IconProps = React.SVGProps<SVGSVGElement>;
const iconProps = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
function AlertTriangle(props: IconProps) { return <svg {...iconProps} {...props}><path d="M10.3 3.4 2.2 18a2 2 0 0 0 1.8 3h16a2 2 0 0 0 1.8-3L13.7 3.4a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>; }
function ChevronRight(props: IconProps) { return <svg {...iconProps} {...props}><path d="m9 18 6-6-6-6"/></svg>; }
function CircleDot(props: IconProps) { return <svg {...iconProps} {...props}><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/></svg>; }
function RefreshCw(props: IconProps) { return <svg {...iconProps} {...props}><path d="M20 6v5h-5"/><path d="M4 18v-5h5"/><path d="M18.5 9A7 7 0 0 0 6.2 6.2L4 8"/><path d="M5.5 15A7 7 0 0 0 17.8 17.8L20 16"/></svg>; }
function Search(props: IconProps) { return <svg {...iconProps} {...props}><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>; }
function ShieldCheck(props: IconProps) { return <svg {...iconProps} {...props}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/></svg>; }
function SlidersHorizontal(props: IconProps) { return <svg {...iconProps} {...props}><path d="M4 6h16M4 12h16M4 18h16"/><path d="M8 4v4M16 10v4M10 16v4"/></svg>; }

const WINDOWS = [{ value: 24, label: "24 ชั่วโมง" }, { value: 168, label: "7 วัน" }, { value: 720, label: "30 วัน" }];
const DECISIONS = [
  ["", "ทุก Decision"], ["block", "Block"], ["would_block", "Would block"],
  ["challenge", "Challenge"], ["would_mfa", "Would MFA"], ["mfa_passed", "MFA passed"],
];
const RESPONSE_STEPS = [
  ["01", "ACKNOWLEDGE", "รับทราบและกำหนดผู้รับผิดชอบ"],
  ["02", "INVESTIGATE", "ตรวจ Timeline, Risk และหลักฐาน"],
  ["03", "CONTAIN", "ปิด Session หรือบล็อกต้นทาง"],
  ["04", "RESOLVE", "สรุปผลและบันทึก Audit"],
] as const;

function formatDateTime(value: string | null) {
  if (!value) return "—";
  return parseUTC(value).toLocaleString("th-TH", {
    timeZone: "Asia/Bangkok", day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  });
}
function formatDecision(value: string | null) { return (value || "unknown").replaceAll("_", " ").toUpperCase(); }
function decisionTone(value: string | null) {
  if (["block", "would_block"].includes(value || "")) return styles.danger;
  if (["challenge", "would_mfa", "would_challenge", "mfa_required"].includes(value || "")) return styles.warning;
  if (["allow", "mfa_passed"].includes(value || "")) return styles.safe;
  return styles.neutral;
}
function riskTone(score: number | null) {
  if (score == null) return styles.neutralRisk;
  if (score >= .85) return styles.criticalRisk;
  if (score >= .6) return styles.highRisk;
  return styles.mediumRisk;
}

export default function IncidentsPage() {
  const [data, setData] = useState<IncidentListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hours, setHours] = useState(168);
  const [decision, setDecision] = useState("");
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [detail, setDetail] = useState<IncidentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [activityPage, setActivityPage] = useState(0);

  const load = useCallback(() => {
    setLoading(true); setError(null);
    const params = new URLSearchParams({ hours: String(hours), limit: "100" });
    if (decision) params.set("decision", decision);
    if (appliedQuery) params.set("q", appliedQuery);
    clientFetch<IncidentListResponse>(`/admin/incidents?${params}`)
      .then(setData)
      .catch((reason) => setError(reason?.detail || "ไม่สามารถโหลดเหตุการณ์ได้"))
      .finally(() => setLoading(false));
  }, [appliedQuery, decision, hours]);

  useEffect(load, [load]);

  const fetchDetail = useCallback((id: string) => {
    setDetailLoading(true);
    clientFetch<IncidentDetail>(`/admin/incidents/${id}`)
      .then(setDetail).catch(() => setDetail(null)).finally(() => setDetailLoading(false));
  }, []);
  function openDetail(row: IncidentRow) { setOpenId(row.id); setDetail(null); fetchDetail(row.id); }
  function submitSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextQuery = query.trim();
    if (nextQuery === appliedQuery) load();
    else setAppliedQuery(nextQuery);
  }

  useEffect(() => { setActivityPage(0); }, [hours, data]);

  const activeWindow = WINDOWS.find((item) => item.value === hours)?.label || "7 วัน";
  // ความเคลื่อนไหว — แสดงครั้งละ 5 รายการ กดดูหน้าถัดไปได้
  const ACTIVITY_PAGE = 5;
  const allActivity = useMemo(() => data?.items ?? [], [data]);
  const activityPages = Math.max(1, Math.ceil(allActivity.length / ACTIVITY_PAGE));
  const latestItems = useMemo(
    () => allActivity.slice(activityPage * ACTIVITY_PAGE, activityPage * ACTIVITY_PAGE + ACTIVITY_PAGE),
    [allActivity, activityPage]
  );
  const kpis = data?.kpis;

  return <>
    <Topbar title="Incidents" />
    <main className={styles.workspace}>
      <section className={styles.command} aria-labelledby="incident-command-title">
        <div className={styles.commandLead}>
          <div><span className={styles.eyebrow}>incident command</span><h1 id="incident-command-title">Incidents</h1></div>
        </div>
        <div className={styles.commandControls}>
          <div className={styles.windowTabs} aria-label="เลือกช่วงเวลา">
            {WINDOWS.map((item) => <button key={item.value} type="button" className={hours === item.value ? styles.activeTab : ""} onClick={() => setHours(item.value)}>{item.label}</button>)}
          </div>
          <button className={styles.refreshButton} type="button" onClick={load} disabled={loading}><RefreshCw aria-hidden="true" className={loading ? styles.spinning : ""} />รีเฟรช</button>
        </div>
      </section>

      <section className={styles.kpis} aria-label="สรุปเหตุการณ์เสี่ยง">
        <Kpi label="TOTAL INCIDENTS" value={kpis?.total} detail={activeWindow} />
        <Kpi label="BLOCKED" value={kpis?.blocked} detail="ถูกระบบระงับ" tone="danger" />
        <Kpi label="CHALLENGED" value={kpis?.challenged} detail="ต้องยืนยันตัวตนเพิ่ม" tone="warning" />
        <Kpi label="ATTACK IP" value={kpis?.attack_ip} detail="ตรงกับ Threat Signal" tone="network" />
      </section>

      {error && <div className={styles.errorBanner} role="alert"><AlertTriangle aria-hidden="true" /><span>{error}</span><button type="button" onClick={load}>ลองใหม่</button></div>}

      <section className={styles.responsePanel} aria-labelledby="response-title">
        <header className={styles.panelHeader}><div><span className={styles.eyebrow}>RESPONSE CONTROL</span><h2 id="response-title">ลำดับการตอบสนอง</h2></div></header>
        <ol>{RESPONSE_STEPS.map(([number, title, description], index) => <li key={number} className={index === 0 ? styles.currentStep : ""}><span>{number}</span><div><strong>{title}</strong><small>{description}</small></div></li>)}</ol>
      </section>

      <section className={styles.operations}>
        <article className={styles.queuePanel}>
          <header className={styles.panelHeader}>
            <div><span className={styles.eyebrow}>TRIAGE QUEUE</span><h2>เหตุการณ์ที่ต้องตรวจสอบ</h2></div>
            <span className={styles.recordCount}><CircleDot aria-hidden="true" />{loading ? "กำลังโหลด" : `${data?.items.length ?? 0} จาก ${data?.total ?? 0} รายการ`}</span>
          </header>
          <div className={styles.toolbar}>
            <form className={styles.searchForm} onSubmit={submitSearch}>
              <Search aria-hidden="true" /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="ค้นหา Incident ID, อีเมล ชื่อผู้ใช้ หรือ IP" aria-label="ค้นหาเหตุการณ์" /><button type="submit">ค้นหา</button>
            </form>
            <label className={styles.decisionFilter}><SlidersHorizontal aria-hidden="true" /><span className={styles.srOnly}>กรองตาม Decision</span><select value={decision} onChange={(e) => setDecision(e.target.value)}>{DECISIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          </div>
          <div className={styles.tableWrap}>
            <table>
              <thead><tr><th>Risk</th><th>เหตุการณ์</th><th>Decision</th><th>ผู้ใช้งาน</th><th>ช่องทาง / ระบบ</th><th>เวลา (Asia/Bangkok)</th><th>สถานะ</th><th><span className={styles.srOnly}>เปิดรายละเอียด</span></th></tr></thead>
              <tbody>
                {loading ? Array.from({ length: 3 }).map((_, i) => <tr key={i} className={styles.skeletonRow}><td colSpan={8}><span /></td></tr>)
                : !data || data.items.length === 0 ? <tr><td colSpan={8} className={styles.emptyState}><ShieldCheck aria-hidden="true" /><strong>ไม่พบเหตุการณ์ในช่วงที่เลือก</strong><span>ลองเปลี่ยนช่วงเวลา ตัวกรอง หรือคำค้นหา</span></td></tr>
                : data.items.map((row) => {
                  const status = STATUS_META[row.status] ?? STATUS_META.expired;
                  return <tr key={row.id} className={`${styles.dataRow} ${openId === row.id ? styles.selectedRow : ""}`} onClick={() => openDetail(row)}>
                    <td><div className={styles.riskCell}><strong>{row.risk_score != null ? row.risk_score.toFixed(2) : "—"}</strong><span><i className={riskTone(row.risk_score)} style={{ width: `${Math.min((row.risk_score ?? 0) * 100, 100)}%` }} /></span></div></td>
                    <td><div className={styles.incidentCell}><strong>{row.top_reason || "ตรวจพบ Session ที่มีความเสี่ยง"}</strong><code>{row.id}</code></div></td>
                    <td><span className={`${styles.statusPill} ${decisionTone(row.decision)}`}>{formatDecision(row.decision)}</span></td>
                    <td><div className={styles.primarySecondary}><strong>{row.full_name || row.user_email || "ไม่ทราบผู้ใช้"}</strong><span>{row.user_email || row.user_type || "—"}</span></div></td>
                    <td><div className={styles.primarySecondary}><strong>{row.channel_label}</strong><span>{row.target}</span></div></td>
                    <td><time className={styles.timeCell}>{formatDateTime(row.created_at)}</time></td>
                    <td><span className={`${styles.statusPill} ${row.status === "active" ? styles.danger : styles.safe}`}>{status.label}</span></td>
                    <td><button type="button" className={styles.rowAction} aria-label={`เปิดรายละเอียด ${row.id}`} onClick={(e) => { e.stopPropagation(); openDetail(row); }}><ChevronRight aria-hidden="true" /></button></td>
                  </tr>;
                })}
              </tbody>
            </table>
          </div>
          {data && data.total > data.items.length && <footer className={styles.tableFooter}>แสดง {data.items.length} จาก {data.total} เหตุการณ์ — ใช้ตัวกรองเพื่อดูข้อมูลเฉพาะเจาะจง</footer>}
        </article>

      </section>

      <section className={styles.activityPanel} aria-labelledby="activity-title">
        <header className={styles.panelHeader}>
          <div><span className={styles.eyebrow}>INCIDENT ACTIVITY</span><h2 id="activity-title">ความเคลื่อนไหวล่าสุด</h2></div>
          {allActivity.length > ACTIVITY_PAGE && (
            <div className={styles.activityPager}>
              <button type="button" onClick={() => setActivityPage((v) => Math.max(0, v - 1))} disabled={activityPage === 0} aria-label="หน้าก่อนหน้า">‹</button>
              <span>{activityPage * ACTIVITY_PAGE + 1}–{Math.min((activityPage + 1) * ACTIVITY_PAGE, allActivity.length)} / {allActivity.length}</span>
              <button type="button" onClick={() => setActivityPage((v) => Math.min(activityPages - 1, v + 1))} disabled={activityPage >= activityPages - 1} aria-label="หน้าถัดไป">›</button>
            </div>
          )}
        </header>
        {latestItems.length ? <div className={styles.activityList}>{latestItems.map((row) => <button key={row.id} type="button" onClick={() => openDetail(row)}><span className={styles.activityDot} /><time>{formatDateTime(row.created_at)}</time><div><strong>{formatDecision(row.decision)} · {row.id}</strong><span>{row.top_reason || `${row.channel_label} → ${row.target}`}</span></div><ChevronRight aria-hidden="true" /></button>)}</div> : <div className={styles.activityEmpty}>ยังไม่มีความเคลื่อนไหวในช่วงที่เลือก</div>}
      </section>
    </main>

    {openId !== null && !detailLoading && detail && <IncidentDetailModal data={detail} onClose={() => { setOpenId(null); setDetail(null); }} onActionDone={() => { if (openId) fetchDetail(openId); load(); }} />}
    {openId !== null && detailLoading && <div className={styles.detailLoading} role="status"><RefreshCw aria-hidden="true" className={styles.spinning} /><span>กำลังโหลดรายละเอียดเหตุการณ์</span></div>}
  </>;
}

function Kpi({ label, value, detail, tone }: { label: string; value?: number; detail: string; tone?: "danger" | "warning" | "network" }) {
  const toneClass = tone === "danger" ? styles.kpiDanger : tone === "warning" ? styles.kpiWarning : tone === "network" ? styles.kpiNetwork : "";
  return <article className={`${styles.kpiCard} ${toneClass}`}><span className={styles.kpiLabel}>{label}</span><strong>{value ?? "—"}</strong><small>{detail}</small></article>;
}
