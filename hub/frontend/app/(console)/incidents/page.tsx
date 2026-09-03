"use client";

/**
 * Incidents — triage list ของ login ที่ RBA flag ว่าเสี่ยง.
 * คลิกแถว → drawer แสดง Incident Summary (Entry→Detected→Impact→Actions).
 */

import { useCallback, useEffect, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";
import { IncidentDetailModal } from "./_components/IncidentDetailModal";
import {
  type IncidentListResponse,
  type IncidentDetail,
  type IncidentRow,
  DECISION_TONE,
  STATUS_META,
} from "./_types";

const WINDOW_OPTIONS = [
  { v: 24, label: "24 ชม." },
  { v: 168, label: "7 วัน" },
  { v: 720, label: "30 วัน" },
];

export default function IncidentsPage() {
  const [data, setData] = useState<IncidentListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hours, setHours] = useState(168);
  const [decision, setDecision] = useState("");
  const [q, setQ] = useState("");

  // drawer
  const [detail, setDetail] = useState<IncidentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    const qs = new URLSearchParams({ hours: String(hours), limit: "100" });
    if (decision) qs.set("decision", decision);
    if (q.trim()) qs.set("q", q.trim());
    clientFetch<IncidentListResponse>(`/admin/incidents?${qs.toString()}`)
      .then(setData)
      .catch((e) => setError(e?.detail || "โหลดไม่สำเร็จ"))
      .finally(() => setLoading(false));
  }, [hours, decision, q]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [hours, decision]);

  const fetchDetail = useCallback((id: string) => {
    setDetailLoading(true);
    clientFetch<IncidentDetail>(`/admin/incidents/${id}`)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  }, []);

  function openDetail(row: IncidentRow) {
    setOpenId(row.id);
    setDetail(null);
    fetchDetail(row.id);
  }

  const kpis = data?.kpis;

  const actions = (
    <div className="cx-live-actions">
      {WINDOW_OPTIONS.map((option) => (
        <button key={option.v} type="button" className={hours === option.v ? "active" : ""} onClick={() => setHours(option.v)}>
          {option.v === 24 ? "24h" : option.v === 168 ? "7d" : "30d"}
        </button>
      ))}
      <button type="button" onClick={load}>↻ รีเฟรชเหตุการณ์</button>
    </div>
  );

  return (
    <>
      <Topbar title="เหตุการณ์เสี่ยง (Incidents)" actions={actions} />
      <main className="cx-document">
        <section className="cx-kpis four" aria-label="สรุปเหตุการณ์เสี่ยง">
          <article className="cx-kpi danger"><span className="mono">TOTAL INCIDENTS</span><strong>{kpis?.total ?? "—"}</strong><small className="mono">{hours} HOURS</small></article>
          <article className="cx-kpi danger"><span className="mono">BLOCKED</span><strong>{kpis?.blocked ?? "—"}</strong><small className="mono">ENFORCED / SHADOW</small></article>
          <article className="cx-kpi"><span className="mono">CHALLENGED</span><strong>{kpis?.challenged ?? "—"}</strong><small className="mono">MFA REQUIRED</small></article>
          <article className="cx-kpi"><span className="mono">ATTACK IP</span><strong>{kpis?.attack_ip ?? "—"}</strong><small className="mono">NETWORK SIGNAL</small></article>
        </section>

        {error && <div className="cx-alert danger" role="alert">{error}</div>}

        <section className="cx-panel">
          <header>
            <div><span className="mono">RISK EVENT QUEUE</span><h2>เหตุการณ์ที่ต้องตรวจสอบ</h2></div>
            <span className="cx-data">{loading ? "LOADING" : `${data?.items.length ?? 0} / ${data?.total ?? 0} RECORDS`}</span>
          </header>
          <div className="cx-toolbar">
            <label><SearchIcon /><input value={q} onChange={(event) => setQ(event.target.value)} onKeyDown={(event) => event.key === "Enter" && load()} placeholder="อีเมล, ชื่อผู้ใช้ หรือ Incident ID..." /></label>
            <select value={decision} onChange={(event) => setDecision(event.target.value)}>
              <option value="">ทุก decision</option>
              <option value="block">block</option>
              <option value="would_block">would_block</option>
              <option value="challenge">challenge</option>
              <option value="would_mfa">would_mfa</option>
              <option value="mfa_passed">mfa_passed</option>
            </select>
            <button type="button" onClick={load}>ค้นหา</button>
          </div>
          <div className="cx-table-wrap">
            <table>
              <thead><tr><th>DETECTED</th><th>IDENTITY</th><th>ENTRY → TARGET</th><th>RISK</th><th>DECISION</th><th>STATUS</th></tr></thead>
              <tbody>
                {loading && <EmptyRow label="กำลังโหลดเหตุการณ์" />}
                {!loading && (!data || data.items.length === 0) && <EmptyRow label="ไม่มีเหตุการณ์เสี่ยงในช่วงที่เลือก" />}
                {!loading && data?.items.map((row) => {
                  const status = STATUS_META[row.status] ?? STATUS_META.expired;
                  const risk = row.risk_score ?? 0;
                  return (
                    <tr key={row.id} onClick={() => openDetail(row)} className={`cx-clickable-row ${openId === row.id ? "is-selected" : ""}`}>
                      <td><code>{row.created_at ? new Date(row.created_at).toISOString().slice(5, 16).replace("T", " ") : "—"}</code><small className="cx-data">{row.id.slice(0, 12)}</small></td>
                      <td><b>{row.full_name || row.user_email || "—"}</b><small className="cx-data">{row.user_email || "UNKNOWN IDENTITY"}</small></td>
                      <td><span>{row.channel_label}</span><small className="cx-data">{row.is_subsystem ? "SUBSYSTEM" : "HUB"} · {row.target}</small></td>
                      <td><Risk value={risk} /></td>
                      <td><span className={`cx-chip ${DECISION_TONE[row.decision || ""] === "danger" ? "danger" : DECISION_TONE[row.decision || ""] === "warn" ? "warn" : "outline"}`}>{row.decision || "—"}</span></td>
                      <td><span className={`cx-chip ${status.tone === "danger" ? "danger" : status.tone === "good" ? "signal" : "outline"}`}>{status.label}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {data && data.total > data.items.length && <div className="cx-pagination"><span className="mono">SHOWING {data.items.length} OF {data.total}</span></div>}
        </section>
      </main>

      {openId !== null && !detailLoading && detail && (
        <IncidentDetailModal data={detail} onClose={() => setOpenId(null)} onActionDone={() => { if (openId) fetchDetail(openId); load(); }} />
      )}
      {openId !== null && detailLoading && (
        <div className="fixed inset-0 z-50 bg-ink-900/50 grid place-items-center">
          <div className="cx-loading-card">กำลังโหลดรายละเอียดเหตุการณ์…</div>
        </div>
      )}
    </>
  );
}

function Risk({ value }: { value: number }) {
  const tone = value >= 0.85 ? "crit" : value >= 0.6 ? "high" : value >= 0.3 ? "mid" : "low";
  return <span className="cx-risk"><i><span className={tone} style={{ width: `${Math.max(2, Math.round(value * 100))}%` }} /></i><b className="mono">{value.toFixed(2)}</b></span>;
}

function EmptyRow({ label }: { label: string }) {
  return <tr><td colSpan={6}><div className="cx-empty"><strong>{label}</strong><span className="mono">NO RISK EVENTS</span></div></td></tr>;
}

function SearchIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>;
}
