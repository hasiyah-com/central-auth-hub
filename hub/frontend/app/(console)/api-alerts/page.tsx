// "use client";

// import { useEffect, useState, useCallback } from "react";
// import { Topbar } from "@/components/Topbar";
// import { StatsCard } from "@/components/StatsCard";
// import { Badge } from "@/components/Badge";
// import { clientFetch } from "@/lib/api";

// // ── Types ──

// type Alert = {
//   id: string;
//   rule: string;
//   severity: string;
//   ip: string | null;
//   user_id: string | null;
//   detail: Record<string, unknown> | null;
//   resolved: boolean;
//   created_at: string | null;
// };

// type AlertsResponse = {
//   data: {
//     alerts: Alert[];
//     total: number;
//     rules: Record<string, string>;
//   };
// };

// type ScanResponse = {
//   scanned_minutes: number;
//   new_alerts: number;
//   alerts: Array<{ id: string; rule: string; severity: string; ip: string | null }>;
// };

// const RULE_ICON: Record<string, string> = {
//   excessive_requests: "",
//   high_error_rate: "",
//   unauthorized_probing: "",
//   bot_pattern: "",
// };

// const SEVERITY_TONE: Record<string, "warn" | "danger"> = {
//   warning: "warn",
//   critical: "danger",
// };

// export default function ApiAlertsPage() {
//   const [data, setData] = useState<AlertsResponse["data"] | null>(null);
//   const [days, setDays] = useState(7);
//   const [error, setError] = useState<string | null>(null);
//   const [scanning, setScanning] = useState(false);
//   const [scanMsg, setScanMsg] = useState<string | null>(null);
//   const [filterRule, setFilterRule] = useState<string>("");
//   const [filterResolved, setFilterResolved] = useState<string>("");

//   const load = useCallback(() => {
//     setError(null);
//     let url = `/admin/api-alerts?days=${days}`;
//     if (filterRule) url += `&rule=${filterRule}`;
//     if (filterResolved === "true") url += "&resolved=true";
//     if (filterResolved === "false") url += "&resolved=false";
//     clientFetch<AlertsResponse>(url)
//       .then((res) => setData(res.data))
//       .catch((e) => setError(e.detail || "โหลด alerts ไม่สำเร็จ"));
//   }, [days, filterRule, filterResolved]);

//   useEffect(load, [load]);

//   async function handleScan() {
//     setScanning(true);
//     setScanMsg(null);
//     try {
//       const res = await clientFetch<ScanResponse>(
//         "/admin/api-alerts/scan?minutes=5",
//         { method: "POST" }
//       );
//       setScanMsg(
//         res.new_alerts > 0
//           ? `พบ ${res.new_alerts} alert ใหม่`
//           : "ไม่พบพฤติกรรมผิดปกติ"
//       );
//       load();
//     } catch (e) {
//       const err = e as { detail?: string };
//       setScanMsg(err.detail || "สแกนไม่สำเร็จ");
//     } finally {
//       setScanning(false);
//     }
//   }

//   async function handleResolve(id: string) {
//     try {
//       await clientFetch(`/admin/api-alerts/${id}/resolve`, { method: "POST" });
//       load();
//     } catch {
//       // silent
//     }
//   }

//   const alerts = data?.alerts ?? [];
//   const critical = alerts.filter((a) => a.severity === "critical" && !a.resolved).length;
//   const warning = alerts.filter((a) => a.severity === "warning" && !a.resolved).length;
//   const resolved = alerts.filter((a) => a.resolved).length;

//   return (
//     <>
//       <Topbar title="API Alerts" />
//       <main className="p-8 max-w-7xl mx-auto w-full">
//         {/* Header */}
//         <div className="mb-6 flex items-end justify-between gap-4 flex-wrap">
//           <div>
//             <h2 className="text-sm font-bold text-ink-500 uppercase tracking-wider">
//               Rule-Based API Anomaly Detection
//             </h2>
//             <p className="text-xs text-ink-400 mt-1">
//               {/* ตรวจจับพฤติกรรม API ผิดปกติจาก request_logs (OWASP API4:2023 + NIST SP 800-228) */}
//             </p>
//           </div>
//           <div className="flex items-center gap-3">
//             <button
//               onClick={handleScan}
//               disabled={scanning}
//               className="px-4 py-2 rounded-lg bg-brand-600 text-white text-sm font-semibold hover:bg-brand-700 disabled:opacity-50 transition"
//             >
//               {scanning ? "กำลังสแกน…" : "สแกนตอนนี้"}
//             </button>
//             <select
//               value={days}
//               onChange={(e) => setDays(Number(e.target.value))}
//               className="px-3 py-2 rounded-lg border border-ink-200 bg-white text-sm focus:outline-none focus:border-brand-500"
//             >
//               <option value={1}>1 วัน</option>
//               <option value={7}>7 วัน</option>
//               <option value={30}>30 วัน</option>
//             </select>
//           </div>
//         </div>

//         {scanMsg && (
//           <div className={`mb-4 p-3 rounded-lg text-sm ${
//             scanMsg.includes("ไม่พบ") || scanMsg.includes("ไม่สำเร็จ")
//               ? "bg-emerald-50 border border-emerald-200 text-emerald-700"
//               : "bg-amber-50 border border-amber-200 text-amber-700"
//           }`}>
//             {scanMsg}
//           </div>
//         )}

//         {error && (
//           <div className="mb-6 p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm">
//             {error}
//           </div>
//         )}

//         {!data && !error && (
//           <div className="text-ink-400 text-sm">กำลังโหลด…</div>
//         )}

//         {data && (
//           <>
//             {/* KPI */}
//             <section className="mb-8">
//               <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
//                 <StatsCard
//                   label="Critical (ยังไม่ตรวจ)"
//                   value={String(critical)}
//                   sub="unauthorized probing"
//                   tone={critical > 0 ? "danger" : "good"}
//                 />
//                 <StatsCard
//                   label="Warning (ยังไม่ตรวจ)"
//                   value={String(warning)}
//                   sub="excessive requests, errors, bots"
//                   tone={warning > 0 ? "warn" : "good"}
//                 />
//                 <StatsCard
//                   label="Resolved"
//                   value={String(resolved)}
//                   sub="ตรวจสอบแล้ว"
//                 />
//               </div>
//             </section>

//             {/* Filters */}
//             <div className="mb-4 flex gap-3 flex-wrap">
//               <select
//                 value={filterRule}
//                 onChange={(e) => setFilterRule(e.target.value)}
//                 className="px-3 py-1.5 rounded-lg border border-ink-200 bg-white text-sm"
//               >
//                 <option value="">ทุกกฎ</option>
//                 {Object.entries(data.rules).map(([key, desc]) => (
//                   <option key={key} value={key}>
//                     {RULE_ICON[key] || ""} {key}
//                   </option>
//                 ))}
//               </select>
//               <select
//                 value={filterResolved}
//                 onChange={(e) => setFilterResolved(e.target.value)}
//                 className="px-3 py-1.5 rounded-lg border border-ink-200 bg-white text-sm"
//               >
//                 <option value="">ทั้งหมด</option>
//                 <option value="false">ยังไม่ตรวจ</option>
//                 <option value="true">ตรวจแล้ว</option>
//               </select>
//             </div>

//             {/* Alert list */}
//             <section>
//               <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
//                 Alerts · {alerts.length} รายการ
//               </h3>
//               <div className="space-y-3">
//                 {alerts.length === 0 ? (
//                   <div className="bg-white rounded-xl border border-ink-200 p-12 text-center text-ink-400">
//                     ไม่มี alert ในช่วงเวลานี้
//                   </div>
//                 ) : (
//                   alerts.map((a) => (
//                     <AlertCard
//                       key={a.id}
//                       alert={a}
//                       onResolve={() => handleResolve(a.id)}
//                     />
//                   ))
//                 )}
//               </div>
//             </section>

//             {/* Rules reference */}
//             <section className="mt-8">
//               <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
//                 กฎที่ตรวจจับ (4 กฎ)
//               </h3>
//               <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
//                 {Object.entries(data.rules).map(([key, desc]) => (
//                   <div
//                     key={key}
//                     className="bg-white rounded-lg border border-ink-200 p-4"
//                   >
//                     <div className="flex items-center gap-2">
//                       <span className="text-lg">{RULE_ICON[key] || ""}</span>
//                       <span className="text-sm font-bold text-ink-900">{key}</span>
//                     </div>
//                     <p className="text-xs text-ink-500 mt-1">{desc}</p>
//                   </div>
//                 ))}
//               </div>
//             </section>
//           </>
//         )}
//       </main>
//     </>
//   );
// }

// // ── Alert Card ──

// function AlertCard({
//   alert,
//   onResolve,
// }: {
//   alert: Alert;
//   onResolve: () => void;
// }) {
//   const icon = RULE_ICON[alert.rule] || "";
//   // eslint-disable-next-line @typescript-eslint/no-explicit-any
//   const detail = (alert.detail || {}) as Record<string, any>;
//   const time = alert.created_at
//     ? new Date(alert.created_at).toISOString().slice(0, 19).replace("T", " ")
//     : "—";

//   return (
//     <div
//       className={`bg-white rounded-xl border shadow-sm p-5 ${
//         alert.resolved
//           ? "border-ink-200 opacity-60"
//           : alert.severity === "critical"
//           ? "border-rose-300"
//           : "border-amber-300"
//       }`}
//     >
//       <div className="flex items-start justify-between gap-4">
//         <div className="flex-1">
//           {/* Header */}
//           <div className="flex items-center gap-2 flex-wrap">
//             {icon && <span className="text-lg">{icon}</span>}
//             <span className="font-bold text-ink-900">{alert.rule}</span>
//             <Badge tone={SEVERITY_TONE[alert.severity] || "warn"}>
//               {alert.severity.toUpperCase()}
//             </Badge>
//             {alert.resolved && <Badge tone="good">RESOLVED</Badge>}
//           </div>

//           {/* Detail */}
//           <div className="mt-2 text-sm text-ink-600">
//             {detail.desc && (
//               <p>{String(detail.desc)}</p>
//             )}
//             <div className="mt-1 flex gap-4 flex-wrap text-xs text-ink-500">
//               {alert.ip && (
//                 <span>
//                   IP: <span className="font-mono">{alert.ip}</span>
//                 </span>
//               )}
//               {detail.count != null && (
//                 <span>
//                   Count: <span className="font-bold">{String(detail.count)}</span>
//                   {detail.threshold && ` / threshold ${String(detail.threshold)}`}
//                 </span>
//               )}
//               {detail.request_count != null && (
//                 <span>
//                   Requests: <span className="font-bold">{String(detail.request_count)}</span>
//                 </span>
//               )}
//               {detail.cv != null && (
//                 <span>
//                   CV: <span className="font-mono">{String(detail.cv)}</span>
//                   {` (max ${String(detail.max_cv)})`}
//                 </span>
//               )}
//               {detail.mean_interval_sec != null && (
//                 <span>
//                   Interval: <span className="font-mono">{String(detail.mean_interval_sec)}s</span>
//                 </span>
//               )}
//               {detail.window_sec != null && (
//                 <span>Window: {String(detail.window_sec)}s</span>
//               )}
//             </div>
//             {Array.isArray(detail.sample_paths) && detail.sample_paths.length > 0 && (
//               <div className="mt-2">
//                 <span className="text-[10px] font-bold text-ink-400 uppercase">
//                   Paths targeted:
//                 </span>
//                 <div className="flex flex-wrap gap-1 mt-1">
//                   {(detail.sample_paths as string[]).map((p, i) => (
//                     <span
//                       key={i}
//                       className="px-2 py-0.5 rounded bg-ink-100 text-[11px] font-mono text-ink-600"
//                     >
//                       {p}
//                     </span>
//                   ))}
//                 </div>
//               </div>
//             )}
//           </div>

//           {/* Time */}
//           <div className="mt-2 text-[11px] font-mono text-ink-400">{time} UTC</div>
//         </div>

//         {/* Actions */}
//         {!alert.resolved && (
//           <button
//             onClick={onResolve}
//             className="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium border border-ink-200 text-ink-600 hover:bg-ink-50 transition"
//           >
//             Resolve
//           </button>
//         )}
//       </div>
//     </div>
//   );
// }

"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";
import styles from "./api-alerts.module.css";

type AlertSeverity = "critical" | "warning" | string;

type ApiAlert = {
  id: string;
  rule: string;
  severity: AlertSeverity;
  ip: string | null;
  user_id: string | null;
  detail: Record<string, unknown> | null;
  resolved: boolean;
  created_at: string | null;
};

type AlertsResponse = {
  data: {
    alerts: ApiAlert[];
    total: number;
    rules: Record<string, string>;
  };
};

type ScanResponse = {
  scanned_minutes: number;
  new_alerts: number;
  alerts: Array<{
    id: string;
    rule: string;
    severity: string;
    ip: string | null;
  }>;
};

type Notice = {
  tone: "success" | "warning" | "error";
  text: string;
};

const RULE_LABELS: Record<string, string> = {
  excessive_requests: "ปริมาณคำขอสูงผิดปกติ",
  high_error_rate: "อัตราข้อผิดพลาดสูง",
  unauthorized_probing: "พยายามเข้าถึง Endpoint โดยไม่ได้รับอนุญาต",
  bot_pattern: "รูปแบบการเรียกใช้งานคล้าย Bot",
};

const PERIOD_OPTIONS = [
  { value: 1, label: "24 ชั่วโมง" },
  { value: 7, label: "7 วัน" },
  { value: 30, label: "30 วัน" },
];

const PAGE_SIZE = 5;

export default function ApiAlertsPage() {
  const [data, setData] = useState<AlertsResponse["data"] | null>(null);
  const [days, setDays] = useState(7);
  const [filterRule, setFilterRule] = useState("");
  const [filterResolved, setFilterResolved] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setNotice(null);

    let url = `/admin/api-alerts?days=${days}`;
    if (filterRule) url += `&rule=${encodeURIComponent(filterRule)}`;
    if (filterResolved === "true") url += "&resolved=true";
    if (filterResolved === "false") url += "&resolved=false";

    try {
      const response = await clientFetch<AlertsResponse>(url);
      setData(response.data);
    } catch (error) {
      const message = getErrorMessage(error, "โหลด API Alerts ไม่สำเร็จ");
      setNotice({ tone: "error", text: message });
    } finally {
      setLoading(false);
    }
  }, [days, filterRule, filterResolved]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleScan() {
    setScanning(true);
    setNotice(null);

    try {
      const response = await clientFetch<ScanResponse>(
        "/admin/api-alerts/scan?minutes=5",
        { method: "POST" },
      );

      setNotice({
        tone: response.new_alerts > 0 ? "warning" : "success",
        text:
          response.new_alerts > 0
            ? `พบ Alert ใหม่ ${response.new_alerts} รายการจากการสแกน ${response.scanned_minutes} นาทีล่าสุด`
            : `ไม่พบความผิดปกติใหม่จากการสแกน ${response.scanned_minutes} นาทีล่าสุด`,
      });
      await load();
    } catch (error) {
      setNotice({
        tone: "error",
        text: getErrorMessage(error, "สแกน API ไม่สำเร็จ"),
      });
    } finally {
      setScanning(false);
    }
  }

  async function handleResolve(id: string) {
    setResolvingId(id);
    setNotice(null);

    try {
      await clientFetch(`/admin/api-alerts/${id}/resolve`, {
        method: "POST",
      });
      setNotice({ tone: "success", text: "ปิด Alert เรียบร้อยแล้ว" });
      await load();
    } catch (error) {
      setNotice({
        tone: "error",
        text: getErrorMessage(error, "ปิด Alert ไม่สำเร็จ"),
      });
    } finally {
      setResolvingId(null);
    }
  }

  const alerts = data?.alerts ?? [];

  const summary = useMemo(() => {
    const open = alerts.filter((alert) => !alert.resolved);
    return {
      open: open.length,
      critical: open.filter((alert) => alert.severity === "critical").length,
      warning: open.filter((alert) => alert.severity === "warning").length,
      resolved: alerts.filter((alert) => alert.resolved).length,
    };
  }, [alerts]);

  const visibleAlerts = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    if (!keyword) return alerts;

    return alerts.filter((alert) => {
      const detail = JSON.stringify(alert.detail ?? {}).toLowerCase();
      return [alert.id, alert.rule, alert.ip ?? "", alert.user_id ?? "", detail]
        .join(" ")
        .toLowerCase()
        .includes(keyword);
    });
  }, [alerts, search]);

  useEffect(() => {
    setPage(1);
  }, [search, filterRule, filterResolved, days, data]);

  const totalPages = Math.max(1, Math.ceil(visibleAlerts.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pagedAlerts = visibleAlerts.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE,
  );

  const periodLabel =
    PERIOD_OPTIONS.find((option) => option.value === days)?.label ?? `${days} วัน`;

  return (
    <>
      <Topbar title="API Alerts" />

      <main className={styles.page}>
        <section className={styles.commandHeader}>
          <div>
            <span className={styles.eyebrow}>
              <span className={styles.liveDot} aria-hidden="true" />
              API SECURITY CONTROL
            </span>
            <h1>เฝ้าระวังการเรียกใช้ API</h1>
            <p>
              ตรวจจับ Request ที่ผิดปกติ จัดลำดับความรุนแรง และติดตามการแก้ไขจากข้อมูลจริง
            </p>
          </div>

          <div className={styles.headerActions}>
            <label className={styles.periodSelect}>
              <span>ช่วงเวลา</span>
              <select value={days} onChange={(event) => setDays(Number(event.target.value))}>
                {PERIOD_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <button
              type="button"
              className={styles.scanButton}
              onClick={() => void handleScan()}
              disabled={scanning}
            >
              <ScanIcon />
              {scanning ? "กำลังสแกน…" : "สแกนตอนนี้"}
            </button>
          </div>
        </section>

        {notice && (
          <div className={`${styles.notice} ${styles[notice.tone]}`} role="status">
            <p>{notice.text}</p>
            <button type="button" onClick={() => setNotice(null)} aria-label="ปิดข้อความ">
              ×
            </button>
          </div>
        )}

        <section className={styles.metrics} aria-label="สรุป API Alerts">
          <MetricCard
            label="OPEN ALERTS"
            value={data ? summary.open : "—"}
            detail={`ยังไม่ปิด · ${periodLabel}`}
            tone="signal"
          />
          <MetricCard
            label="CRITICAL"
            value={data ? summary.critical : "—"}
            detail="ต้องตรวจสอบทันที"
            tone="critical"
          />
          <MetricCard
            label="WARNING"
            value={data ? summary.warning : "—"}
            detail="ควรตรวจสอบพฤติกรรม"
            tone="warning"
          />
          <MetricCard
            label="RESOLVED"
            value={data ? summary.resolved : "—"}
            detail={`ปิดแล้ว · ${periodLabel}`}
            tone="neutral"
          />
        </section>

        <div className={styles.contentGrid}>
          <section className={styles.alertPanel}>
            <header className={styles.panelHeader}>
              <div>
                <span className={styles.sectionLabel}>DETECTION QUEUE</span>
                <h2>รายการแจ้งเตือน</h2>
              </div>
              <span className={styles.resultCount}>
                {loading ? "กำลังโหลด" : `${visibleAlerts.length} รายการ`}
              </span>
            </header>

            <div className={styles.toolbar}>
              <label className={styles.searchBox}>
                <SearchIcon />
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="ค้นหา Rule, IP, User ID หรือรายละเอียด"
                  aria-label="ค้นหา API Alert"
                />
              </label>

              <select
                value={filterRule}
                onChange={(event) => setFilterRule(event.target.value)}
                aria-label="กรองตามกฎ"
              >
                <option value="">ทุกกฎ</option>
                {Object.entries(data?.rules ?? {}).map(([key]) => (
                  <option key={key} value={key}>
                    {key}
                  </option>
                ))}
              </select>

              <select
                value={filterResolved}
                onChange={(event) => setFilterResolved(event.target.value)}
                aria-label="กรองตามสถานะ"
              >
                <option value="">ทุกสถานะ</option>
                <option value="false">กำลังตรวจสอบ</option>
                <option value="true">ปิดแล้ว</option>
              </select>

              <button type="button" className={styles.refreshButton} onClick={() => void load()}>
                รีเฟรช
              </button>
            </div>

            <div className={styles.tableWrap}>
              <div className={styles.tableHeader} aria-hidden="true">
                <span>SEVERITY</span>
                <span>RULE / DETAIL</span>
                <span>SOURCE</span>
                <span>DETECTED</span>
                <span>STATUS</span>
                <span>ACTION</span>
              </div>

              {loading ? (
                <LoadingRows />
              ) : visibleAlerts.length === 0 ? (
                <EmptyState
                  filtered={Boolean(search || filterRule || filterResolved)}
                  onReset={() => {
                    setSearch("");
                    setFilterRule("");
                    setFilterResolved("");
                  }}
                />
              ) : (
                <>
                  <div className={styles.rows}>
                    {pagedAlerts.map((alert) => (
                      <AlertRow
                        key={alert.id}
                        alert={alert}
                        resolving={resolvingId === alert.id}
                        onResolve={() => void handleResolve(alert.id)}
                      />
                    ))}
                  </div>

                  {visibleAlerts.length > PAGE_SIZE && (
                    <div className={styles.pager}>
                      <span className={styles.pageInfo}>
                        หน้า {currentPage} / {totalPages} · ทั้งหมด {visibleAlerts.length} รายการ
                      </span>
                      <div className={styles.pagerActions}>
                        <button
                          type="button"
                          onClick={() => setPage((p) => Math.max(1, p - 1))}
                          disabled={currentPage <= 1}
                        >
                          ‹ ก่อนหน้า
                        </button>
                        <button
                          type="button"
                          onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                          disabled={currentPage >= totalPages}
                        >
                          ถัดไป ›
                        </button>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </section>

          <aside className={styles.rulesPanel}>
            <header className={styles.panelHeader}>
              <div>
                <span className={styles.sectionLabel}>RULE SET</span>
                <h2>กฎที่กำลังตรวจจับ</h2>
              </div>
              <span className={styles.ruleStatus}>ACTIVE</span>
            </header>

            <div className={styles.ruleList}>
              {Object.entries(data?.rules ?? RULE_LABELS).map(([key, description], index) => (
                <article key={key}>
                  <span className={styles.ruleIndex}>{String(index + 1).padStart(2, "0")}</span>
                  <div>
                    <code>{key}</code>
                    <p>{description || RULE_LABELS[key] || "ตรวจจับพฤติกรรม API ผิดปกติ"}</p>
                  </div>
                  <span className={styles.ruleDot} aria-label="ทำงานอยู่" />
                </article>
              ))}
            </div>

            <footer className={styles.rulesFooter}>
              <span>SCAN WINDOW</span>
              <strong>5 MIN</strong>
            </footer>
          </aside>
        </div>
      </main>
    </>
  );
}

function MetricCard({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: number | string;
  detail: string;
  tone: "signal" | "critical" | "warning" | "neutral";
}) {
  return (
    <article className={`${styles.metricCard} ${styles[tone]}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function AlertRow({
  alert,
  resolving,
  onResolve,
}: {
  alert: ApiAlert;
  resolving: boolean;
  onResolve: () => void;
}) {
  const severityClass =
    alert.severity === "critical" ? styles.criticalRow : styles.warningRow;
  const details = getDetailPairs(alert.detail).filter(
    ([key, value]) => key !== "desc" && String(value).length <= 16,
  );

  return (
    <article
      className={`${styles.alertRow} ${severityClass} ${
        alert.resolved ? styles.resolvedRow : ""
      }`}
    >
      <div className={styles.severityCell} data-label="SEVERITY">
        <span className={styles.severityMark} />
        <strong>{alert.severity.toUpperCase()}</strong>
      </div>

      <div className={styles.ruleCell} data-label="RULE / DETAIL">
        <div className={styles.ruleTitle}>
          <code>{alert.rule}</code>
          <span>{RULE_LABELS[alert.rule] ?? "ตรวจพบพฤติกรรม API ผิดปกติ"}</span>
        </div>

        {details.length > 0 && (
          <div className={styles.detailChips}>
            {details.slice(0, 4).map(([key, value]) => (
              <span key={key}>
                <b>{formatDetailKey(key)}</b>
                <code>{formatDetailValue(value)}</code>
              </span>
            ))}
          </div>
        )}
      </div>

      <div className={styles.sourceCell} data-label="SOURCE">
        <code>{alert.ip || "—"}</code>
        <span>{alert.user_id ? `USER ${shortId(alert.user_id)}` : "UNATTRIBUTED"}</span>
      </div>

      <div className={styles.timeCell} data-label="DETECTED">
        <time dateTime={alert.created_at ?? undefined}>{formatDate(alert.created_at)}</time>
        <span>ASIA/BANGKOK</span>
      </div>

      <div className={styles.statusCell} data-label="STATUS">
        <span className={alert.resolved ? styles.resolvedBadge : styles.openBadge}>
          {alert.resolved ? "RESOLVED" : "OPEN"}
        </span>
      </div>

      <div className={styles.actionCell} data-label="ACTION">
        {alert.resolved ? (
          <span className={styles.doneMark}>ปิดแล้ว</span>
        ) : (
          <button type="button" onClick={onResolve} disabled={resolving}>
            {resolving ? "กำลังปิด…" : "Resolve"}
          </button>
        )}
      </div>
    </article>
  );
}

function LoadingRows() {
  return (
    <div className={styles.loadingRows} aria-label="กำลังโหลดข้อมูล">
      {[0, 1, 2].map((item) => (
        <span key={item} />
      ))}
    </div>
  );
}

function EmptyState({ filtered, onReset }: { filtered: boolean; onReset: () => void }) {
  return (
    <div className={styles.emptyState}>
      <div className={styles.emptyIcon} aria-hidden="true">
        <span />
      </div>
      <strong>{filtered ? "ไม่พบ Alert ที่ตรงกับตัวกรอง" : "ไม่พบ API Alert ในช่วงเวลานี้"}</strong>
      <p>{filtered ? "ลองเปลี่ยนคำค้นหรือสถานะ" : "ระบบยังคงตรวจสอบ Request ตามกฎที่เปิดใช้งาน"}</p>
      {filtered && (
        <button type="button" onClick={onReset}>
          ล้างตัวกรอง
        </button>
      )}
    </div>
  );
}

function ScanIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 7V4h3M17 4h3v3M20 17v3h-3M7 20H4v-3" />
      <circle cx="12" cy="12" r="3.5" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4 4" />
    </svg>
  );
}

function getErrorMessage(error: unknown, fallback: string) {
  if (typeof error === "object" && error !== null && "detail" in error) {
    const detail = (error as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function getDetailPairs(detail: ApiAlert["detail"]) {
  if (!detail) return [] as Array<[string, unknown]>;
  return Object.entries(detail).filter(([, value]) => {
    return value !== null && value !== undefined && value !== "" && !Array.isArray(value);
  });
}

function formatDetailKey(key: string) {
  return key.replaceAll("_", " ").toUpperCase();
}

function formatDetailValue(value: unknown) {
  if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function shortId(value: string) {
  return value.length > 12 ? `${value.slice(0, 8)}…` : value;
}

function formatDate(value: string | null) {
  if (!value) return "—";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat("th-TH", {
    timeZone: "Asia/Bangkok",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}
