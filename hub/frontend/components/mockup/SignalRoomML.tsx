"use client";

import Link from "next/link";
import styles from "./SignalRoomML.module.css";

type Row = Record<string, unknown>;

function asObject(value: unknown): Row {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
}

function first(source: Row, keys: string[], fallback: unknown = "—") {
  for (const key of keys) {
    const value = source[key];
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return fallback;
}

function scoreOf(row: Row): number {
  const raw = Number(first(row, ["risk_score", "anomaly_score", "score"], 0));
  return Number.isFinite(raw) ? Math.max(0, Math.min(1, raw)) : 0;
}

function percent(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${n <= 1 ? (n * 100).toFixed(1) : n.toFixed(1)}%`;
}

function count(value: unknown): string {
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString("th-TH") : "—";
}

function tone(score: number) {
  return score >= .85 ? styles.critical : score >= .6 ? styles.high : score >= .3 ? styles.medium : styles.low;
}

function decisionTone(decision: string) {
  const value = decision.toUpperCase();
  if (value.includes("BLOCK")) return styles.dangerBadge;
  if (value.includes("MFA") || value.includes("CHALLENGE")) return styles.warningBadge;
  if (value.includes("WARN")) return styles.infoBadge;
  return styles.safeBadge;
}

function featuresOf(row: Row): Array<[string, number]> {
  const raw = first(row, ["top_features", "shap_values", "features", "explanation"], []);
  if (Array.isArray(raw)) {
    return raw.slice(0, 3).map((item, index) => {
      if (item && typeof item === "object") {
        const obj = item as Row;
        return [String(first(obj, ["feature", "name", "key"], `feature_${index + 1}`)), Number(first(obj, ["value", "contribution", "score"], 0))];
      }
      return [String(item), 0];
    });
  }
  if (raw && typeof raw === "object") {
    return Object.entries(raw as Row).slice(0, 3).map(([key, value]) => [key, Number(value)]);
  }
  return [];
}

export function SignalRoomML({ data, rows }: { data: unknown; rows: Row[] }) {
  const root = asObject(data);
  const overview = asObject(first(root, ["data", "overview"], root));
  const decisions = asObject(first(overview, ["decision_distribution", "decisions", "decision_counts"], {}));
  const total = Number(first(overview, ["total_sessions", "sessions_total", "total"], rows.length));
  const anomalyRate = first(overview, ["anomaly_rate", "anomalous_rate"], undefined);
  const challenged = first(overview, ["challenged", "mfa_required", "challenge_count"], undefined);
  const blocked = first(overview, ["blocked", "blocked_count"], undefined);
  const feedback = first(overview, ["feedback_queue", "unlabeled_count", "pending_feedback"], undefined);
  const allow = Number(first(decisions, ["allow", "ALLOW", "pass"], 0));
  const mfa = Number(first(decisions, ["mfa", "MFA", "mfa_required", "MFA_REQUIRED"], 0));
  const warn = Number(first(decisions, ["warn", "WARN", "would_warn"], 0));
  const block = Number(first(decisions, ["block", "BLOCK", "blocked"], 0));
  const distribution = [
    ["ALLOW", allow, styles.allow],
    ["MFA", mfa, styles.mfa],
    ["WARN", warn, styles.warn],
    ["BLOCK", block, styles.block],
  ] as const;
  const maxDecision = Math.max(allow, mfa, warn, block, 1);
  const trend = rows.slice(0, 12).reverse().map(scoreOf);
  const points = trend.length > 1
    ? trend.map((value, index) => `${20 + index * (560 / (trend.length - 1))},${150 - value * 125}`).join(" ")
    : "";

  return (
    <div className={styles.page}>
      <section className={styles.runtime}>
        <div className={styles.runtimeHeading}>
          <span>MODEL RUNTIME</span>
          <h2>4-Layer Risk Engine</h2>
          <p>สถานะการประเมินความเสี่ยงของระบบ</p>
        </div>
        <div className={styles.runtimeMeta}>
          <span className={styles.online}><i /> ONLINE</span>
          <code>{String(first(overview, ["model_version", "version"], "version —"))}</code>
        </div>
        <div className={styles.layers}>
          {[
            ["L1", "Rules", "Policy signals"],
            ["L2", "Behavior", "User baseline"],
            ["L3", "Anomaly Model", "Session pattern"],
            ["L4", "Aggregate", "Final decision"],
          ].map(([id, name, detail]) => (
            <div className={styles.layer} key={id}>
              <span>{id}</span>
              <div><b>{name}</b><small>{detail}</small></div>
              <i className={styles.ready}>READY</i>
            </div>
          ))}
        </div>
      </section>

      <section className={styles.kpis}>
        <article><span>ANOMALY RATE</span><strong>{percent(anomalyRate)}</strong><small>ช่วงข้อมูลล่าสุด</small></article>
        <article><span>CHALLENGED</span><strong>{count(challenged)}</strong><small>MFA / Challenge</small></article>
        <article className={styles.alertKpi}><span>BLOCKED</span><strong>{count(blocked)}</strong><small>Session ที่ถูกป้องกัน</small></article>
        <article><span>FEEDBACK QUEUE</span><strong>{count(feedback)}</strong><small>รอตรวจสอบ Ground truth</small></article>
      </section>

      <section className={styles.overview}>
        <article className={styles.panel}>
          <header><div><span>DECISION DISTRIBUTION</span><h2>สัดส่วนผลการตัดสินใจ</h2></div><b>{count(total)} sessions</b></header>
          <div className={styles.distribution}>
            {distribution.map(([name, value, color]) => (
              <div className={styles.distributionRow} key={name}>
                <span>{name}</span>
                <i><em className={color} style={{ width: `${Math.max(2, value / maxDecision * 100)}%` }} /></i>
                <b>{count(value)}</b>
              </div>
            ))}
          </div>
        </article>

        <article className={styles.panel}>
          <header><div><span>RISK TREND</span><h2>แนวโน้มความเสี่ยงล่าสุด</h2></div><b>{trend.length} events</b></header>
          <div className={styles.chart}>
            {points ? (
              <svg viewBox="0 0 600 170" role="img" aria-label="กราฟแนวโน้มคะแนนความเสี่ยง">
                <g><line x1="20" y1="25" x2="580" y2="25" /><line x1="20" y1="75" x2="580" y2="75" /><line x1="20" y1="125" x2="580" y2="125" /><line x1="20" y1="150" x2="580" y2="150" /></g>
                <polyline points={points} />
              </svg>
            ) : <div className={styles.empty}>ยังไม่มีข้อมูลเพียงพอสำหรับแสดงกราฟ</div>}
          </div>
        </article>
      </section>

      <section className={styles.sessions}>
        <header>
          <div><span>ANOMALOUS SESSIONS</span><h2>Session ที่ต้องตรวจสอบ</h2></div>
          <small>ข้อมูลจาก API จริง · อ่านอย่างเดียว</small>
        </header>
        <div className={styles.sessionList}>
          {rows.length ? rows.slice(0, 10).map((row, index) => {
            const score = scoreOf(row);
            const decision = String(first(row, ["decision", "action", "status"], "UNKNOWN"));
            const id = String(first(row, ["session_id", "id", "event_id"], `SESSION-${index + 1}`));
            const user = String(first(row, ["email", "user_email", "user_id", "subject"], "ไม่ระบุผู้ใช้"));
            const features = featuresOf(row);
            return (
              <article className={styles.session} key={id}>
                <div className={styles.identity}><code>{id}</code><b>{user}</b><small>{String(first(row, ["created_at", "timestamp", "time"], "—"))}</small></div>
                <div className={styles.risk}><strong className={tone(score)}>{score.toFixed(2)}</strong><i><em className={tone(score)} style={{ width: `${score * 100}%` }} /></i></div>
                <div className={styles.features}>
                  <span>TOP CONTRIBUTIONS</span>
                  {features.length ? features.map(([name, value]) => <div key={name}><code>{name}</code><i><em style={{ width: `${Math.min(100, Math.abs(value) * 250)}%` }} /></i><b>{value >= 0 ? "+" : ""}{value.toFixed(2)}</b></div>) : <small>ไม่มี SHAP contribution</small>}
                </div>
                <div className={styles.decision}><span className={decisionTone(decision)}>{decision}</span><Link href="/ui-mockup/risk-detail">ดูรายละเอียด →</Link></div>
              </article>
            );
          }) : <div className={styles.empty}>ไม่มี Session ผิดปกติในช่วงข้อมูลนี้</div>}
        </div>
      </section>
    </div>
  );
}
