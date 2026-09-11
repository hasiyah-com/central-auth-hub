"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { SlidePanel } from "@/components/SlidePanel";
import { clientFetch } from "@/lib/api";
import { AnomalyTable } from "./_components/AnomalyTable";
import { SessionDetailPanel } from "./_components/SessionDetailPanel";
import type { Anomaly, Overview } from "./_types";
import styles from "./ml-dashboard.module.css";

type SortMode = "score" | "recent";

const LAYERS = [
  { id: "L1", name: "Rules", detail: "Policy signals", state: "ACTIVE" },
  { id: "L2", name: "Behavior", detail: "User baseline", state: "ACTIVE" },
  { id: "L3", name: "Isolation Forest", detail: "Anomaly signal", state: "SHADOW" },
  { id: "L4", name: "Aggregate", detail: "Access decision", state: "ACTIVE" },
] as const;

export default function MLPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [days, setDays] = useState(7);
  const [sortMode, setSortMode] = useState<SortMode>("recent");
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Anomaly | null>(null);

  const load = useCallback(() => {
    setOverview(null);
    setError(null);
    clientFetch<Overview>(`/admin/ml/overview?days=${days}&sort=${sortMode}&limit=50`)
      .then(setOverview)
      .catch((reason) => setError(reason.detail || "โหลดข้อมูล ML ไม่สำเร็จ"));
  }, [days, sortMode]);

  useEffect(load, [load]);

  const metrics = useMemo(() => {
    const decisions = overview?.data.decision_breakdown ?? {};
    const total = overview?.data.total_logins ?? 0;
    const challenged = (decisions.mfa ?? 0) + (decisions.challenge ?? 0) +
      (decisions.would_mfa ?? 0) + (decisions.would_challenge ?? 0);
    const blocked = (decisions.block ?? 0) + (decisions.would_block ?? 0);
    const flagged = challenged + blocked + (decisions.warn ?? 0) + (decisions.would_warn ?? 0);
    return { decisions, total, challenged, blocked, anomalyRate: total ? (flagged / total) * 100 : 0 };
  }, [overview]);

  return (
    <>
      <Topbar title="ML / Anomaly" />
      <main className={styles.page}>
        <section className={styles.runtime}>
          <div className={styles.runtimeIntro}>
            <div className={styles.eyebrow}><span className={styles.liveDot} /> MODEL RUNTIME</div>
            <h1>4-Layer Risk Engine</h1>
            <p>ติดตามคะแนนความเสี่ยงและผลการตัดสินใจของทุก Login Session</p>
          </div>
          <div className={styles.runtimeState}>
            <span className={overview ? styles.online : error ? styles.offline : styles.loading}>
              <i /> {overview ? "ONLINE" : error ? "UNAVAILABLE" : "CONNECTING"}
            </span>
            <strong>{overview?.meta.shadow_mode ? "SHADOW MODE" : "POLICY MODE"}</strong>
          </div>
        </section>

        {/* ไปป์ไลน์ 4 ชั้น — แยกเป็นบล็อกของตัวเอง เต็มความกว้าง */}
        <section className={styles.pipeline}>
          {LAYERS.map((layer, index) => {
            const isShadow = layer.state === "SHADOW";
            return (
              <div
                className={isShadow ? `${styles.layer} ${styles.layerShadow}` : styles.layer}
                key={layer.id}
              >
                <span className={styles.layerId}>{layer.id}</span>
                {/* ชื่อบรรทัดบน / คำอธิบาย+สถานะบรรทัดล่าง */}
                <b>{layer.name}</b>
                <div className={styles.layerMeta}>
                  <small>{layer.detail}</small>
                  <em className={isShadow ? styles.shadow : styles.active}>{layer.state}</em>
                </div>
                {index < LAYERS.length - 1 && (
                  <span className={styles.connector} aria-hidden="true" />
                )}
              </div>
            );
          })}
        </section>

        <div className={styles.toolbar}>
          <div><span className={styles.eyebrow}>RISK OPERATIONS</span><h2>ภาพรวมการประเมินความเสี่ยง</h2></div>
          <div className={styles.toolbarActions}>
            <span className={styles.rangeText}>{overview ? `${formatDate(overview.data.range.from)} – ${formatDate(overview.data.range.to)}` : "กำลังอ่านช่วงข้อมูล"}</span>
            <label><span className="sr-only">ช่วงเวลา</span><select value={days} onChange={(event) => setDays(Number(event.target.value))}><option value={1}>24 ชั่วโมง</option><option value={7}>7 วัน</option><option value={30}>30 วัน</option><option value={90}>90 วัน</option></select></label>
            <button type="button" onClick={load}>รีเฟรช</button>
          </div>
        </div>

        {error && <div className={styles.error} role="alert"><span>{error}</span><button type="button" onClick={load}>ลองใหม่</button></div>}

        {!overview && !error ? <LoadingState /> : overview && (
          <>
            <section className={styles.kpis} aria-label="ตัวชี้วัด ML">
              <Metric label="Sessions" value={formatNumber(metrics.total)} detail="ประเมินแล้วทั้งหมด" />
              <Metric label="Anomaly rate" value={`${metrics.anomalyRate.toFixed(1)}%`} detail="Session ที่ต้องตรวจสอบ" tone={metrics.anomalyRate >= 10 ? "danger" : "default"} />
              <Metric label="Challenge / MFA" value={formatNumber(metrics.challenged)} detail="รวมผลจริงและ Shadow" tone="warn" />
              <Metric label="Blocked" value={formatNumber(metrics.blocked)} detail="รวม Block และ Would block" tone="danger" />
            </section>

            <section className={styles.analytics}>
              <article className={styles.panel}>
                <PanelHeader eyebrow="SCORE DISTRIBUTION" title="การกระจายคะแนนความเสี่ยง" meta={`${overview.data.score_histogram.length} ช่วงคะแนน`} />
                <Histogram rows={overview.data.score_histogram} />
              </article>
              <article className={styles.panel}>
                <PanelHeader eyebrow="DECISION OUTPUT" title="ผลการตัดสินใจ" meta={`${formatNumber(metrics.total)} sessions`} />
                <DecisionBreakdown decisions={metrics.decisions} total={metrics.total} />
                <Link className={styles.thresholdLink} href="/ml/threshold"><span><small>THRESHOLD</small><b>ปรับค่าการตัดสินใจ</b></span><code>MFA {overview.meta.thresholds.mfa.toFixed(2)} · BLOCK {overview.meta.thresholds.block.toFixed(2)}</code><span aria-hidden="true">→</span></Link>
              </article>
            </section>

            <section className={styles.sessions}>
              <div className={styles.sessionsHeader}>
                <div><span className={styles.eyebrow}>SESSION EVIDENCE</span><h2>{sortMode === "recent" ? "Session ล่าสุด" : "Session ความเสี่ยงสูง"}</h2><p>เลือกแถวเพื่อดูคะแนนทั้ง 4 ชั้น หลักฐาน และบันทึก Ground Truth</p></div>
                <div className={styles.sortControl} aria-label="เรียงข้อมูล"><button type="button" className={sortMode === "recent" ? styles.selected : ""} onClick={() => setSortMode("recent")}>ล่าสุด</button><button type="button" className={sortMode === "score" ? styles.selected : ""} onClick={() => setSortMode("score")}>คะแนนสูง</button></div>
              </div>
              <div className={styles.tableWrap}><AnomalyTable rows={overview.data.top_anomalies} onRowClick={setSelected} emptyMessage="ไม่พบ Session ในช่วงเวลานี้" showSubsystem /></div>
            </section>
          </>
        )}
      </main>

      <SlidePanel open={!!selected} onClose={() => setSelected(null)} title="Session Detail">
        {selected && <SessionDetailPanel session={selected} onFeedbackSaved={() => { load(); setSelected(null); }} />}
      </SlidePanel>
    </>
  );
}

function Metric({ label, value, detail, tone = "default" }: { label: string; value: string; detail: string; tone?: "default" | "warn" | "danger" }) {
  return <article className={`${styles.metric} ${styles[tone]}`}><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>;
}

function PanelHeader({ eyebrow, title, meta }: { eyebrow: string; title: string; meta: string }) {
  return <header className={styles.panelHeader}><div><span>{eyebrow}</span><h3>{title}</h3></div><b>{meta}</b></header>;
}

function Histogram({ rows }: { rows: Array<{ bucket: string; count: number }> }) {
  const max = Math.max(...rows.map((row) => row.count), 1);
  return <div className={styles.histogram}><div className={styles.bars}>{rows.map((row, index) => <div className={styles.bucket} key={row.bucket}><span>{row.count}</span><i><em className={index >= 7 ? styles.blockBar : index >= 4 ? styles.mfaBar : styles.passBar} style={{ height: `${Math.max(3, (row.count / max) * 100)}%` }} /></i><small>{row.bucket}</small></div>)}</div><div className={styles.zones}><span>LOW · PASS</span><span>MFA ZONE</span><span>HIGH · BLOCK</span></div></div>;
}

function DecisionBreakdown({ decisions, total }: { decisions: Record<string, number>; total: number }) {
  const groups = [
    { label: "ALLOW", value: (decisions.allow ?? 0) + (decisions.pass ?? 0), className: styles.passBar },
    { label: "MFA / CHALLENGE", value: (decisions.mfa ?? 0) + (decisions.challenge ?? 0) + (decisions.would_mfa ?? 0) + (decisions.would_challenge ?? 0), className: styles.mfaBar },
    { label: "WARN", value: (decisions.warn ?? 0) + (decisions.would_warn ?? 0), className: styles.warnBar },
    { label: "BLOCK", value: (decisions.block ?? 0) + (decisions.would_block ?? 0), className: styles.blockBar },
  ];
  return <div className={styles.decisions}>{groups.map((group) => <div className={styles.decisionRow} key={group.label}><span>{group.label}</span><i><em className={group.className} style={{ width: `${total ? Math.max(2, (group.value / total) * 100) : 0}%` }} /></i><b>{formatNumber(group.value)}</b><small>{total ? `${((group.value / total) * 100).toFixed(0)}%` : "0%"}</small></div>)}</div>;
}

function LoadingState() { return <div className={styles.loadingState} aria-label="กำลังโหลดข้อมูล ML"><div /><div /><div /><div /></div>; }
function formatNumber(value: number) { return value.toLocaleString("th-TH"); }
function formatDate(value: string) { return new Intl.DateTimeFormat("th-TH", { day: "2-digit", month: "short", year: "2-digit", timeZone: "Asia/Bangkok" }).format(new Date(value)); }
