"use client";

import { useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/Badge";
import { clientFetch } from "@/lib/api";
import type { Anomaly, UserSession, FeedbackResponse } from "../_types";
import { DECISION_TONE, DEVICE_ICON, FEEDBACK_LABELS } from "../_types";

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

        {/* Risk Reasons */}
        {session.risk_reasons && session.risk_reasons.length > 0 && (
          <div className="mt-3 p-3 rounded-lg bg-ink-50 border border-ink-200">
            <div className="text-[10px] font-bold text-ink-400 uppercase tracking-wider mb-1">
              Reasons
            </div>
            <div className="flex flex-wrap gap-1">
              {session.risk_reasons.map((r, i) => (
                <span
                  key={i}
                  className="px-2 py-0.5 rounded bg-ink-200 text-[11px] font-mono text-ink-700"
                >
                  {r}
                </span>
              ))}
            </div>
          </div>
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
