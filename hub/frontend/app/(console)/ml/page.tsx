"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { SlidePanel } from "@/components/SlidePanel";
import { clientFetch } from "@/lib/api";
import { ScoreHistogram } from "./_components/ScoreHistogram";
import { SessionDetailPanel } from "./_components/SessionDetailPanel";
import type { Overview, Anomaly } from "./_types";

type SortMode = "score" | "recent";

export default function MLPage() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [days, setDays] = useState(7);
  const [sortMode, setSortMode] = useState<SortMode>("recent");
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Anomaly | null>(null);

  const load = useCallback(() => {
    setOv(null);
    setError(null);
    // sort=recent → เห็น session ใหม่ทุกครั้ง / sort=score → top anomalies เดิม
    clientFetch<Overview>(
      `/admin/ml/overview?days=${days}&sort=${sortMode}&limit=50`
    )
      .then(setOv)
      .catch((e) => setError(e.detail || "โหลด ML overview ไม่สำเร็จ"));
  }, [days, sortMode]);

  useEffect(load, [load]);

  const fmt = (n: number) => n.toLocaleString("en-US");
  const dec = ov?.data.decision_breakdown ?? {};
  const total = ov?.data.total_logins ?? 0;
  const anomalyCount =
    (dec.mfa ?? 0) +
    (dec.block ?? 0) +
    (dec.would_mfa ?? 0) +
    (dec.would_block ?? 0);
  const anomalyRate = total > 0 ? ((anomalyCount / total) * 100).toFixed(1) : "0.0";

  const decisions = [
    { key: "allow", label: "ALLOW", value: dec.allow ?? dec.pass ?? 0, tone: "ok" },
    { key: "mfa", label: "MFA", value: (dec.mfa ?? 0) + (dec.would_mfa ?? 0), tone: "info" },
    { key: "warn", label: "WARN", value: (dec.warn ?? 0) + (dec.would_warn ?? 0), tone: "warn" },
    { key: "block", label: "BLOCK", value: (dec.block ?? 0) + (dec.would_block ?? 0), tone: "danger" },
  ];
  const layers = [
    { id: "L1", name: "Rules", meta: "Policy signals" },
    { id: "L2", name: "Behavior", meta: "User baseline" },
    { id: "L3", name: "Isolation Forest", meta: "Anomaly model" },
    { id: "L4", name: "Aggregate", meta: "Final decision" },
  ];

  const actions = (
    <div className="cx-command-actions">
      {ov && <span className={`cx-chip ${ov.meta.shadow_mode ? "warn" : "danger"}`}>{ov.meta.shadow_mode ? "SHADOW MODE" : "ENFORCING"}</span>}
      <Link href="/ml/threshold" className="cx-ml-threshold-link">ปรับ Threshold</Link>
    </div>
  );

  return (
    <>
      <Topbar title="ML / ความผิดปกติ" actions={actions} />
      <main className="cx-document">
        {error && <div className="cx-alert danger" role="alert">{error}</div>}
        <div className="cx-ml-page">
          <section className="cx-ml-runtime">
            <div><span className="mono"><i className="cx-dot"><i /></i> MODEL RUNTIME</span><h2>4-Layer Risk Engine</h2><p>ประเมินความเสี่ยงแบบลำดับชั้นก่อนออกผลตัดสินใจ</p></div>
            <div className="cx-ml-layers">
              {layers.map((layer) => <article key={layer.id}><span className="mono">{layer.id}</span><div><b>{layer.name}</b><small>{layer.meta}</small></div><code className="mono">LIVE</code></article>)}
            </div>
            <aside><span className="cx-chip signal"><i className="cx-dot"><i /></i>ONLINE</span><span className="mono">{ov?.meta.shadow_mode ? "SHADOW" : "ENFORCING"}</span><b className="mono">{ov ? `${days}D` : "—"}</b><small>ANALYSIS WINDOW</small></aside>
          </section>

          <section className="cx-ml-kpis">
            <article><span className="mono">TOTAL LOGINS</span><strong className="mono">{ov ? fmt(total) : "—"}</strong><small>sessions scored</small></article>
            <article><span className="mono">ANOMALY RATE</span><strong className="mono">{ov ? `${anomalyRate}%` : "—"}</strong><small>{anomalyCount} flagged sessions</small></article>
            <article><span className="mono">CHALLENGED</span><strong className="mono">{ov ? fmt((dec.mfa ?? 0) + (dec.would_mfa ?? 0)) : "—"}</strong><small>MFA live + shadow</small></article>
            <article className="danger"><span className="mono">BLOCKED</span><strong className="mono">{ov ? fmt((dec.block ?? 0) + (dec.would_block ?? 0)) : "—"}</strong><small>block live + shadow</small></article>
          </section>

          <section className="cx-ml-overview">
            <article className="cx-panel cx-ml-decisions">
              <header><div><span className="mono">DECISION DISTRIBUTION · {days}D</span><h2>สัดส่วนผลการตัดสินใจ</h2></div><span className="cx-chip outline">{fmt(total)} SESSIONS</span></header>
              <div>
                {decisions.map((item) => {
                  const percentage = total > 0 ? (item.value / total) * 100 : 0;
                  return <section key={item.key}><div><b className="mono">{item.label}</b><strong className="mono">{percentage.toFixed(1)}%</strong></div><i><span className={item.tone} style={{ width: `${percentage}%` }} /></i></section>;
                })}
              </div>
              <footer>{decisions.map((item) => <span key={item.key}><i className={item.tone}/>{item.label}<b className="mono">{fmt(item.value)}</b></span>)}</footer>
            </article>

            <article className="cx-panel cx-ml-trend">
              <header><div><span className="mono">RISK DISTRIBUTION · {days}D</span><h2>การกระจายคะแนนความเสี่ยง</h2></div>
                <select value={days} onChange={(event) => setDays(Number(event.target.value))}><option value={1}>1 วัน</option><option value={7}>7 วัน</option><option value={30}>30 วัน</option><option value={90}>90 วัน</option></select>
              </header>
              {ov ? <ScoreHistogram histogram={ov.data.score_histogram} /> : <div className="cx-empty"><strong>กำลังโหลดข้อมูล ML</strong><span className="mono">GET /ADMIN/ML/OVERVIEW</span></div>}
              {ov && <footer><span>MFA THRESHOLD <b className="mono">{ov.meta.thresholds.mfa}</b></span><span>BLOCK THRESHOLD <b className="mono danger">{ov.meta.thresholds.block}</b></span></footer>}
            </article>
          </section>

          <section className="cx-panel cx-ml-sessions">
            <header>
              <div><span className="mono">ANOMALOUS SESSIONS · PRIORITY ORDER</span><h2>Session ที่ต้องตรวจสอบ</h2></div>
              <div className="cx-ml-session-controls">
                <button type="button" className={sortMode === "recent" ? "active" : ""} onClick={() => setSortMode("recent")}>ล่าสุด</button>
                <button type="button" className={sortMode === "score" ? "active" : ""} onClick={() => setSortMode("score")}>Risk สูงสุด</button>
              </div>
            </header>
            <div className="cx-ml-session-list">
              {!ov && <div className="cx-empty"><strong>กำลังโหลด Session</strong><span className="mono">WAITING FOR API</span></div>}
              {ov && ov.data.top_anomalies.length === 0 && <div className="cx-empty"><strong>ไม่พบ Session ผิดปกติ</strong><span className="mono">NO ANOMALOUS SESSIONS</span></div>}
              {ov?.data.top_anomalies.map((session) => {
                const risk = session.risk_score ?? session.score ?? 0;
                const features = session.risk_breakdown?.iforest_explanation?.slice(0, 3) ?? [];
                return (
                  <article key={session.session_id} onClick={() => setSelected(session)}>
                    <div className="cx-ml-session-id"><code className="mono">{session.session_id.slice(0, 12)}</code><time className="mono">{new Date(session.created_at).toLocaleString("th-TH", { timeZone: "Asia/Bangkok" })}</time></div>
                    <div className="cx-ml-user"><b>{session.user_email}</b><Link href={`/ml/users/${session.user_id}`} onClick={(event) => event.stopPropagation()}>เปิด ML Profile →</Link></div>
                    <div className="cx-ml-score"><strong className="mono">{risk.toFixed(2)}</strong><Risk value={risk} /></div>
                    <div className="cx-ml-shap">
                      <span className="mono">TOP RISK CONTRIBUTIONS</span>
                      {features.length > 0 ? features.map((feature) => <div key={feature.feature}><code className="mono">{feature.feature}</code><i><span style={{ width: `${Math.min(100, Math.abs(feature.shap) * 260)}%` }} /></i><b className="mono">{feature.shap >= 0 ? "+" : ""}{feature.shap.toFixed(2)}</b></div>) : <small className="cx-data">{session.risk_reasons?.slice(0, 3).join(" · ") || "ไม่มี SHAP explanation"}</small>}
                    </div>
                    <div className="cx-ml-decision"><span className={`cx-chip ${decisionTone(session.decision)}`}>{(session.decision || "UNKNOWN").toUpperCase()}</span><small>{session.subsystem_name || "Hub-direct"}</small></div>
                    <div className="cx-ml-label"><button type="button" onClick={(event) => { event.stopPropagation(); setSelected(session); }}>ตรวจสอบรายละเอียด</button></div>
                  </article>
                );
              })}
            </div>
          </section>
        </div>
      </main>

      <SlidePanel open={!!selected} onClose={() => setSelected(null)} title="Session Detail">
        {selected && <SessionDetailPanel session={selected} onFeedbackSaved={() => { load(); setSelected(null); }} />}
      </SlidePanel>
    </>
  );
}

function Risk({ value }: { value: number }) {
  const tone = value >= 0.85 ? "crit" : value >= 0.6 ? "high" : value >= 0.3 ? "mid" : "low";
  return <span className="cx-risk"><i><span className={tone} style={{ width: `${Math.max(2, Math.round(value * 100))}%` }} /></i></span>;
}

function decisionTone(value: string | null) {
  if (["block", "would_block"].includes(value || "")) return "danger";
  if (["mfa", "challenge", "would_mfa", "would_challenge", "warn"].includes(value || "")) return "warn";
  return "signal";
}
