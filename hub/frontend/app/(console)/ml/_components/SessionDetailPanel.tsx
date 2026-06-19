"use client";

import { useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/Badge";
import { clientFetch } from "@/lib/api";
import type {
  Anomaly,
  UserSession,
  FeedbackResponse,
  ShapContribution,
} from "../_types";
import { DECISION_TONE, DEVICE_ICON, FEEDBACK_LABELS, featureLabelTh } from "../_types";

type SessionData = Anomaly | (UserSession & { user_email?: string; user_id?: string; session_id?: string; subsystem_name?: string });

type Props = {
  session: SessionData;
  onFeedbackSaved?: () => void;
  /** ซ่อน link "ดูประวัติ user" เมื่ออยู่ใน user timeline อยู่แล้ว */
  hideUserLink?: boolean;
};

export function SessionDetailPanel({ session, onFeedbackSaved, hideUserLink }: Props) {
  // Normalize IDs ให้ใช้ได้ทั้ง Anomaly และ UserSession
  const sessionId = "session_id" in session ? session.session_id : (session as UserSession).id;
  const userId = "user_id" in session ? session.user_id : undefined;
  const email = "user_email" in session ? session.user_email : undefined;
  const subsystemName = "subsystem_name" in session ? session.subsystem_name : undefined;
  const score = session.score ?? 0;

  // Feedback form state
  const [label, setLabel] = useState<string>("");
  const [note, setNote] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  // Attack IP toggle state
  const [attackIp, setAttackIp] = useState(session.is_attack_ip);
  const [attackIpBusy, setAttackIpBusy] = useState(false);

  async function submitFeedback() {
    if (!label || !sessionId) return;
    setBusy(true);
    setMsg(null);
    try {
      await clientFetch<FeedbackResponse>(
        `/admin/ml/sessions/${sessionId}/feedback`,
        {
          method: "POST",
          body: JSON.stringify({ label, note: note.trim() || null }),
        }
      );
      setMsg({ kind: "ok", text: "บันทึก feedback สำเร็จ" });
      setConfirming(false);
      onFeedbackSaved?.();
    } catch (e) {
      const err = e as { detail?: string };
      setMsg({ kind: "err", text: err.detail || "บันทึกไม่สำเร็จ" });
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  }

  async function toggleAttackIp() {
    if (!sessionId) return;
    setAttackIpBusy(true);
    try {
      const res = await clientFetch<{ is_attack_ip: boolean }>(
        `/admin/ml/sessions/${sessionId}/toggle-attack-ip`,
        { method: "POST" }
      );
      setAttackIp(res.is_attack_ip);
      onFeedbackSaved?.();
    } catch {
      // silent
    } finally {
      setAttackIpBusy(false);
    }
  }

  const riskScore = session.risk_score ?? score;
  const riskPct = Math.round(riskScore * 100);
  const riskColor =
    riskScore >= 0.8 ? "bg-rose-500" : riskScore >= 0.5 ? "bg-amber-500" : riskScore >= 0.3 ? "bg-yellow-400" : "bg-emerald-500";
  const deviceIcon = DEVICE_ICON[session.device_type || "unknown"] || DEVICE_ICON.unknown;
  const bd = session.risk_breakdown;

  return (
    <div className="space-y-6">
      {/* ── 1. Risk Score header ── */}
      <div>
        <div className="flex items-center gap-4">
          <span className="text-4xl font-extrabold tabular-nums text-ink-900">
            {riskScore.toFixed(3)}
          </span>
          <Badge tone={DECISION_TONE[session.decision || "unknown"] || "default"}>
            {(session.decision || "unknown").toUpperCase()}
          </Badge>
        </div>
        <div className="mt-2 h-2 w-full bg-ink-100 rounded-full overflow-hidden">
          <div className={`h-full ${riskColor}`} style={{ width: `${riskPct}%` }} />
        </div>
        <div className="mt-1 text-[10px] text-ink-400">
          Risk Score (4-Layer) · 0.000 – 1.000
          {score != null && <span className="ml-2">| IForest raw: {score.toFixed(2)}</span>}
        </div>

        {/* Risk Breakdown — 3 layers */}
        {bd && (
          <div className="mt-3 grid grid-cols-3 gap-2">
            <BreakdownBar label="Rule" value={bd.rule} max={1} color="bg-blue-500" />
            <BreakdownBar label="Behavior" value={bd.behavior} max={1} color="bg-purple-500" />
            <BreakdownBar label="IForest" value={bd.iforest} max={0.4} color="bg-amber-500" />
          </div>
        )}

        {/* Reasons (Layer 1 + 2) — bar style matching SHAP for visual parity.
            Rules only fire when a signal is suspicious, so every bar here is
            anomaly-direction by definition (no green). Hard blocks (IP
            blacklist, impossible travel) have no numeric weight — render as
            full-width red bars so they read as "maxed out". */}
        {session.risk_reasons && session.risk_reasons.length > 0 && (
          <RuleBreakdown reasons={session.risk_reasons} />
        )}

        {/* SHAP — Layer 3 (IForest) per-feature contributions.
            Only renders when the ML service actually returned an explanation
            (newer ml-service versions with shap installed). Sign-convention:
            positive shap = pushed score TOWARD anomaly (red bar);
            negative = pushed toward normal (green bar). */}
        {bd?.iforest_explanation && bd.iforest_explanation.length > 0 && (
          <ShapBreakdown items={bd.iforest_explanation} />
        )}
      </div>

      {/* ── 2. Detail grid ── */}
      <div className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
        {email && (
          <DetailRow label="Email" value={email} span={2} />
        )}
        {subsystemName !== undefined && (
          <DetailRow
            label="Subsystem"
            value={subsystemName || "Hub-direct (Admin Console)"}
            span={2}
          />
        )}
        <DetailRow label="IP" value={session.ip || "—"} mono />
        <DetailRow
          label="Country / City"
          value={
            [session.geo_country?.toUpperCase(), session.geo_city]
              .filter(Boolean)
              .join(" · ") || "—"
          }
        />
        <DetailRow
          label="Device"
          value={
            <span>
              {deviceIcon} {session.device_type || "—"}
            </span>
          }
        />
        <DetailRow label="Browser" value={session.browser || "—"} />
        <DetailRow label="OS" value={session.os_name || "—"} />
        <DetailRow
          label="Time (UTC)"
          value={new Date(session.created_at).toISOString().slice(0, 19).replace("T", " ")}
          mono
        />
        <DetailRow
          label="Attack IP"
          value={
            <div className="flex items-center gap-2">
              {attackIp ? (
                <Badge tone="danger">YES</Badge>
              ) : (
                <span className="text-ink-400">No</span>
              )}
              <button
                onClick={toggleAttackIp}
                disabled={attackIpBusy}
                className="px-2 py-0.5 rounded text-[10px] font-semibold border border-ink-200 text-ink-500 hover:bg-ink-50 disabled:opacity-50 transition"
              >
                {attackIpBusy ? "…" : attackIp ? "Unmark" : "Mark"}
              </button>
            </div>
          }
        />
        <DetailRow
          label="Account Takeover"
          value={
            <div>
              {session.is_account_takeover ? (
                <Badge tone="pink">YES</Badge>
              ) : (
                <span className="text-ink-400">No</span>
              )}
              <div className="text-[9px] text-ink-400 mt-0.5">
                ตั้งจาก Feedback (TP=Yes)
              </div>
            </div>
          }
        />
      </div>

      {/* ── 3. Feedback form ── */}
      <div className="border-t border-ink-200 pt-5">
        <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
          Ground Truth Feedback
        </h3>

        <div className="space-y-2">
          {FEEDBACK_LABELS.map((fb) => (
            <label
              key={fb.value}
              className="flex items-start gap-3 p-2 rounded-lg hover:bg-ink-50 cursor-pointer transition"
            >
              <input
                type="radio"
                name="feedback_label"
                value={fb.value}
                checked={label === fb.value}
                onChange={() => {
                  setLabel(fb.value);
                  setConfirming(false);
                  setMsg(null);
                }}
                className="mt-0.5 accent-brand-600"
              />
              <div>
                <div className="text-sm font-semibold text-ink-900">{fb.label}</div>
                <div className="text-xs text-ink-500">{fb.desc}</div>
              </div>
            </label>
          ))}
        </div>

        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="หมายเหตุ (optional)…"
          rows={2}
          className="mt-3 w-full px-3 py-2 rounded-lg border border-ink-200 text-sm focus:outline-none focus:border-brand-500 resize-none"
        />

        {/* Two-step confirm pattern */}
        {!confirming ? (
          <button
            onClick={() => setConfirming(true)}
            disabled={!label}
            className="mt-3 w-full px-4 py-2.5 rounded-lg bg-brand-600 text-white text-sm font-semibold hover:bg-brand-700 disabled:opacity-40 disabled:cursor-not-allowed transition"
          >
            บันทึก Feedback
          </button>
        ) : (
          <div className="mt-3 flex gap-2">
            <button
              onClick={submitFeedback}
              disabled={busy}
              className="flex-1 px-4 py-2.5 rounded-lg bg-emerald-600 text-white text-sm font-semibold hover:bg-emerald-700 disabled:opacity-50 transition"
            >
              {busy ? "กำลังบันทึก…" : "ยืนยัน"}
            </button>
            <button
              onClick={() => setConfirming(false)}
              className="px-4 py-2.5 rounded-lg border border-ink-200 text-sm font-medium text-ink-600 hover:bg-ink-50 transition"
            >
              ยกเลิก
            </button>
          </div>
        )}

        {msg && (
          <div
            className={`mt-3 p-3 rounded-lg text-sm ${
              msg.kind === "ok"
                ? "bg-emerald-50 border border-emerald-200 text-emerald-700"
                : "bg-rose-50 border border-rose-200 text-rose-700"
            }`}
          >
            {msg.text}
          </div>
        )}
      </div>

      {/* ── 4. Actions ── */}
      {!hideUserLink && userId && (
        <div className="border-t border-ink-200 pt-4">
          <Link
            href={`/ml/users/${userId}`}
            className="inline-flex items-center gap-1 text-sm font-semibold text-brand-600 hover:text-brand-700 transition"
          >
            ดูประวัติ user &rarr;
          </Link>
        </div>
      )}
    </div>
  );
}

// ── Helper: Detail row ──

function DetailRow({
  label,
  value,
  mono,
  span,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
  span?: number;
}) {
  return (
    <div className={span === 2 ? "col-span-2" : ""}>
      <div className="text-[10px] font-bold text-ink-400 uppercase tracking-wider">
        {label}
      </div>
      <div className={`mt-0.5 text-ink-900 ${mono ? "font-mono text-xs" : ""}`}>
        {value}
      </div>
    </div>
  );
}

function BreakdownBar({
  label,
  value,
  max,
  color,
}: {
  label: string;
  value: number;
  max: number;
  color: string;
}) {
  const pct = Math.round((value / max) * 100);
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-[10px] font-bold text-ink-500 uppercase">{label}</span>
        <span className="text-xs font-mono font-bold text-ink-900">{value.toFixed(2)}</span>
      </div>
      <div className="h-1.5 bg-ink-100 rounded-full overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
    </div>
  );
}

/** SHAP per-feature breakdown for Layer 3 (IForest).
 *
 *  Bars are normalized to the MAX absolute SHAP in the list — relative
 *  magnitudes are what humans read at a glance, not absolute SHAP units
 *  (which are decision_function space, unbounded for IForest).
 *
 *  Direction → color:
 *    anomaly (positive shap) = rose-500 (this feature made score WORSE)
 *    normal  (negative shap) = emerald-500 (pushed score TOWARD normal)
 */
function ShapBreakdown({ items }: { items: ShapContribution[] }) {
  const maxAbs = Math.max(...items.map((i) => Math.abs(i.shap)), 0.001);
  const COLLAPSED = 6;
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? items : items.slice(0, COLLAPSED);

  return (
    <div className="mt-3 p-3 rounded-lg bg-amber-50/50 border border-amber-200">
      <div className="text-[10px] font-bold text-amber-700 uppercase tracking-wider mb-2 flex items-center gap-1.5">
        <span>SHAP (Layer 3 · IForest)</span>
        <span
          className="text-amber-500 font-normal normal-case tracking-normal"
          title="ทุก feature เรียงตาม |SHAP|. แดง = ดันไป anomaly, เขียว = ดันไป normal. (หน่วย SHAP = decision-function ไม่ใช่ 0-1)"
        >
          {showAll ? `ทั้งหมด ${items.length}` : `top ${Math.min(COLLAPSED, items.length)} / ${items.length}`}
        </span>
      </div>
      <div className="space-y-1.5">
        {shown.map((it, i) => {
          const pct = Math.round((Math.abs(it.shap) / maxAbs) * 100);
          const isAnomaly = it.direction === "anomaly";
          const bar = isAnomaly ? "bg-rose-500" : "bg-emerald-500";
          return (
            <div key={i}>
              <div className="flex items-baseline justify-between gap-2 mb-0.5">
                <span className="text-[11px] text-ink-700 truncate" title={it.feature}>
                  {featureLabelTh(it.feature)}
                  <span className="ml-1.5 font-mono text-ink-400">
                    = {fmtFeatureValue(it.value)}
                  </span>
                </span>
                <span
                  className={`text-[10px] font-mono font-bold ${
                    isAnomaly ? "text-rose-600" : "text-emerald-600"
                  }`}
                >
                  {isAnomaly ? "+" : ""}
                  {it.shap.toFixed(3)}
                </span>
              </div>
              <div className="h-1.5 bg-ink-100 rounded-full overflow-hidden">
                <div className={`h-full ${bar}`} style={{ width: `${pct}%` }} />
              </div>
            </div>
          );
        })}
      </div>
      {items.length > COLLAPSED && (
        <button
          onClick={() => setShowAll((v) => !v)}
          className="mt-2 text-[11px] font-medium text-amber-700 hover:text-amber-900 hover:underline"
        >
          {showAll ? "▲ ย่อ" : `▼ ดูทั้งหมด (${items.length} features)`}
        </button>
      )}
    </div>
  );
}

/** Display feature values nicely: integers show no decimal, floats show 2dp. */
function fmtFeatureValue(v: number): string {
  return Number.isInteger(v) ? v.toString() : v.toFixed(2);
}

/** Parse a raw L1+2 reason string into structured parts so we can render it
 *  with the same bar layout as SHAP. Formats this handles (see rule_engine.py
 *  and behavior_profiling.py for source-of-truth):
 *
 *    "is_new_device (+0.30)"
 *    "is_thailand=0 (+0.10)"
 *    "failed_logins_24h>=3 (+0.20)"
 *    "hours_diff=8.2 >= 6 (+0.20)"
 *    "weekend_mismatch (+0.10)"
 *    "multi_account_ip=7 > 5 (+0.25)"
 *    "no_history (cold start)"                       ← no weight
 *    "ip_blacklisted (203.0.113.42)"                 ← hard block, no weight
 *    "impossible_travel: TH → US in 0.5h (< 1h)"     ← hard block
 *    "country_change_count_30d=8 >= 8 (hard block)"  ← hard block
 *    "skipped (hard block)"                          ← layer 2 skipped
 */
type ParsedReason = {
  feature: string;
  detail: string | null;
  weight: number | null;
  isHardBlock: boolean;
};

function parseReason(raw: string): ParsedReason {
  const isHardBlock =
    raw.includes("hard block") ||
    raw.startsWith("ip_blacklisted") ||
    raw.startsWith("impossible_travel");

  // Pull off the trailing "(+0.XX)" weight if present
  const weightMatch = raw.match(/\(\+(\d+(?:\.\d+)?)\)\s*$/);
  const weight = weightMatch ? parseFloat(weightMatch[1]) : null;
  let body = weightMatch ? raw.slice(0, weightMatch.index).trim() : raw.trim();

  // Layer-2 "skipped" — leave as is
  if (body.startsWith("skipped")) {
    return { feature: "(layer skipped)", detail: null, weight: null, isHardBlock: true };
  }

  // "impossible_travel: TH → US in 0.5h (< 1h)"
  if (body.startsWith("impossible_travel")) {
    const colonIdx = body.indexOf(":");
    return {
      feature: "impossible_travel",
      detail: colonIdx >= 0 ? body.slice(colonIdx + 1).trim() : null,
      weight,
      isHardBlock: true,
    };
  }

  // "ip_blacklisted (203.0.113.42)" — feature only, detail in parens
  if (body.startsWith("ip_blacklisted")) {
    const m = body.match(/^ip_blacklisted\s*\(([^)]+)\)/);
    return {
      feature: "ip_blacklisted",
      detail: m ? m[1] : null,
      weight,
      isHardBlock: true,
    };
  }

  // Strip a trailing " (hard block)" marker so feature parse below stays clean
  body = body.replace(/\s*\(hard block\)\s*$/, "").trim();

  // Strip a trailing " (cold start)" marker (layer 2 cold start) and treat as
  // a non-weighted reason
  if (/\(cold start\)\s*$/.test(body)) {
    return {
      feature: body.replace(/\s*\(cold start\)\s*$/, "").trim() || "cold_start",
      detail: "cold start",
      weight,
      isHardBlock: false,
    };
  }

  // Generic: "feature[=value] [op threshold]" — feature is alnum/underscore at start
  const featMatch = body.match(/^([A-Za-z_][A-Za-z0-9_]*)/);
  const feature = featMatch ? featMatch[1] : body;
  const rest = body.slice(feature.length).trim();
  // Drop leading "=" or operator chars so detail reads cleanly
  const detail = rest.replace(/^=\s*/, "").trim() || null;

  return { feature, detail, weight, isHardBlock };
}

/** Layer 1 + 2 bar breakdown — visual mirror of ShapBreakdown.
 *
 *  Why bars (vs the old chips): admins need to scan WHICH features fired and
 *  HOW MUCH each contributed. A row of chips makes them all look equal; bars
 *  ranked by weight surface the dominant signal at a glance.
 *
 *  Sizing: bar width is `weight / maxWeight`. Hard-block reasons have no
 *  numeric weight — they render full width because they alone can decide
 *  the outcome.
 */
function RuleBreakdown({ reasons }: { reasons: string[] }) {
  const parsed = reasons.map(parseReason);
  // Max weight in the list — used to normalize bar widths. Falls back to 0.4
  // (typical L1 weight) when no reason carries a number.
  const maxWeight = Math.max(
    ...parsed.map((p) => p.weight ?? 0),
    0.001,
  );

  return (
    <div className="mt-3 p-3 rounded-lg bg-rose-50/40 border border-rose-200">
      <div className="text-[10px] font-bold text-rose-700 uppercase tracking-wider mb-2 flex items-center gap-1.5">
        <span>Reasons (Layer 1 + 2)</span>
        <span
          className="text-rose-400 font-normal normal-case tracking-normal"
          title="Hard-coded rules + behavior profile hits. All bars are anomaly direction."
        >
          ({parsed.length})
        </span>
      </div>
      <div className="space-y-1.5">
        {parsed.map((p, i) => {
          const pct = p.isHardBlock
            ? 100
            : p.weight != null
              ? Math.round((p.weight / maxWeight) * 100)
              : 50; // unknown weight — half bar so it's visible but not dominant
          return (
            <div key={i}>
              <div className="flex items-baseline justify-between gap-2 mb-0.5">
                <span className="text-[11px] font-mono text-ink-700 truncate">
                  {p.feature}
                  {p.detail && (
                    <span className="ml-1.5 text-ink-400">= {p.detail}</span>
                  )}
                </span>
                <span className="text-[10px] font-mono font-bold text-rose-600 whitespace-nowrap">
                  {p.isHardBlock
                    ? "HARD BLOCK"
                    : p.weight != null
                      ? `+${p.weight.toFixed(2)}`
                      : "—"}
                </span>
              </div>
              <div className="h-1.5 bg-ink-100 rounded-full overflow-hidden">
                <div className="h-full bg-rose-500" style={{ width: `${pct}%` }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
