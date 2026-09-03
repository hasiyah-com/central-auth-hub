"use client";

/**
 * IncidentDetailModal — มุมมองเต็มจอของ incident เดียว จัดระเบียบรอบ
 * "Why → What happened → What should I do" (admin ไม่ต้องไล่อ่านทั้งหมด):
 *   - Incident Summary (Why/What/What-to-do + impact)
 *   - Attack Path (เข้าทางไหน → ผลลัพธ์)
 *   - Risk Analysis (ย่อ: score/decision/top reasons + View ML Explanation)
 *   - Recommended Actions (จัดกลุ่มตามหมวด) — ทำงานจริงผ่าน step-up
 */

import { useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/Badge";
import { mutateWithStepup } from "@/lib/passkey";
import { parseUTC } from "@/lib/format";
import {
  type IncidentDetail,
  type IncidentAction,
  type TimelineEvent,
  DECISION_TONE,
  STATUS_META,
  SEVERITY_META,
  RISK_LEVEL_META,
  ACTION_CATEGORY_META,
  NODE_STATUS_CLS,
  AUDIT_ACTION_LABEL,
} from "../_types";

// Backend ส่ง timestamp เป็น naive UTC → parseUTC เติม Z แล้วแปลงเป็นเวลาไทย
// (Asia/Bangkok) ให้ตรงกับหน้าอื่นทั้งระบบ. locale "th-TH" → วันที่แบบ พ.ศ.
// ("11/08/2569 15:51:51") ให้ตรงกับตาราง ML/anomaly. (B53)
function fmt(iso: string | null, withDate = true): string {
  if (!iso) return "—";
  const opts: Intl.DateTimeFormatOptions = {
    timeZone: "Asia/Bangkok",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  };
  if (withDate) {
    opts.year = "numeric";
    opts.month = "2-digit";
    opts.day = "2-digit";
  }
  return parseUTC(iso).toLocaleString("th-TH", opts);
}

type Props = {
  data: IncidentDetail;
  onClose: () => void;
  onActionDone: () => void;
};

export function IncidentDetailModal({ data, onClose, onActionDone }: Props) {
  const { entry, risk, reasons, timeline, system_response, actions, stats_7d, user } =
    data;
  const [verifying, setVerifying] = useState(false);
  const [busyType, setBusyType] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [showML, setShowML] = useState(false);

  const lvl = RISK_LEVEL_META[risk.level] ?? RISK_LEVEL_META.low;
  const status = STATUS_META[system_response.session_status] ?? STATUS_META.expired;
  const riskPct = Math.round(risk.score * 100);
  const riskColor =
    risk.score >= 0.85 ? "bg-rose-500" : risk.score >= 0.7 ? "bg-amber-500" : "bg-yellow-400";
  const initial = (user.full_name || user.email || "?").charAt(0).toUpperCase();
  // forensic timeline 2 แถบ: สิ่งที่บัญชีนี้ทำ / ระบบ·แอดมินตอบโต้
  const acctEvents = timeline.filter((e) => e.strand === "account");
  const respEvents = timeline.filter((e) => e.strand !== "account");

  // group actions by category (คงลำดับ root_cause → … → configuration)
  const CATEGORY_ORDER = [
    "root_cause",
    "authentication",
    "network",
    "account",
    "subsystem",
    "configuration",
  ];
  const grouped = CATEGORY_ORDER.map((cat) => ({
    cat,
    items: actions.filter((a) => a.category === cat),
  })).filter((g) => g.items.length > 0);

  async function runAction(a: IncidentAction) {
    if (!a.enabled) return;
    if (a.type === "reset_passkey" || a.type === "block_ip") {
      if (!confirm(`ยืนยัน: ${a.title}?`)) return;
    }
    setBusyType(a.type);
    setMsg(null);
    try {
      const r = await mutateWithStepup<{ message?: string; ok?: boolean }>(
        `/admin/incidents/${data.id}/action`,
        { method: "POST", body: JSON.stringify({ action: a.type }) },
        setVerifying
      );
      setMsg({ kind: r.ok === false ? "err" : "ok", text: r.message || "สำเร็จ" });
      onActionDone();
    } catch (e) {
      const d = (e as { detail?: unknown })?.detail;
      const code = typeof d === "object" && d ? (d as { code?: string }).code : undefined;
      if (code === "no_passkey") {
        setMsg({ kind: "err", text: "ต้องมี Passkey เพื่อยืนยัน — ตั้งค่าที่หน้าบัญชี" });
      } else if (e instanceof DOMException && e.name === "NotAllowedError") {
        setMsg({ kind: "err", text: "ยกเลิกการยืนยัน Passkey" });
      } else {
        setMsg({ kind: "err", text: typeof d === "string" ? d : "ดำเนินการไม่สำเร็จ" });
      }
    } finally {
      setBusyType(null);
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-ink-900/50 overflow-y-auto p-4">
      {verifying && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-2xl px-6 py-5 shadow-xl flex items-center gap-3 text-sm">
            <span className="animate-pulse text-lg">🔐</span>
            กำลังยืนยันด้วย Passkey…
          </div>
        </div>
      )}

      <div className="mx-auto max-w-6xl bg-ink-50 overflow-hidden cx-single-page">
        {/* ── header ── */}
        <div className="bg-white px-6 py-4 border-b border-ink-200 flex items-center justify-between sticky top-0 z-10">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-extrabold text-ink-900">Incident Detail</h1>
            <Badge tone={lvl.tone}>🛡 {lvl.label}</Badge>
          </div>
          <button onClick={onClose} className="text-ink-400 hover:text-ink-700 text-2xl leading-none">
            ×
          </button>
        </div>

        {/* ── summary bar ── */}
        <div className="bg-white px-6 py-5 border-b border-ink-200 grid grid-cols-2 md:grid-cols-4 gap-5">
          <div className="col-span-2 flex items-center gap-3">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 grid place-items-center text-white text-xl font-extrabold shrink-0">
              {initial}
            </div>
            <div className="min-w-0">
              <div className="text-lg font-extrabold text-ink-900 truncate">{user.full_name || "—"}</div>
              <div className="text-xs text-ink-500 font-mono truncate">{user.email}</div>
              <div className="mt-1 flex items-center gap-2">
                {user.user_type && <Badge tone="brand">{user.user_type}</Badge>}
                {user.status && (
                  <Badge tone={user.status === "active" ? "good" : "danger"}>{user.status}</Badge>
                )}
              </div>
            </div>
          </div>
          <div>
            <div className="text-[10px] font-bold text-ink-400 uppercase">Risk Score</div>
            <div className="text-3xl font-extrabold tabular-nums text-rose-600 leading-tight">
              {risk.score.toFixed(3)}
              <span className="text-sm text-ink-400 font-normal"> / 1.000</span>
            </div>
            <div className="mt-1 h-1.5 w-full bg-ink-100 rounded-full overflow-hidden">
              <div className={`h-full ${riskColor}`} style={{ width: `${riskPct}%` }} />
            </div>
          </div>
          <div>
            <div className="text-[10px] font-bold text-ink-400 uppercase">Decision</div>
            <Badge tone={DECISION_TONE[system_response.decision || ""] || "default"}>
              {(system_response.decision || "—").toUpperCase()}
            </Badge>
            <div className="text-[10px] text-ink-400 mt-1.5 font-mono">{fmt(data.created_at)} น.</div>
            <div className="text-[10px] text-ink-400 font-mono">{data.incident_display_id}</div>
          </div>
        </div>

        <div className="cx-dossier">
          {/* ══ Incident Summary — Why → What → What to do ══ */}
          <div className="bg-white border border-brand-200 p-5 cx-reference-summary">
            <h3 className="text-sm font-extrabold text-ink-800 mb-3 flex items-center gap-1.5">
              <span>🧭</span> สรุปเหตุการณ์ (Incident Summary)
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <SummaryCol tone="rose" head="WHY · ทำไมเสี่ยง" body={data.summary.why} />
              <SummaryCol tone="amber" head="WHAT · เกิดอะไรขึ้น" body={data.summary.what} />
              <SummaryCol tone="emerald" head="WHAT TO DO · ควรทำอะไร" body={data.summary.what_to_do} />
            </div>
            {/* impact statements */}
            <div className="mt-4 flex flex-wrap gap-2">
              {data.impact.statements.map((s, i) => (
                <span
                  key={i}
                  className={
                    "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border " +
                    (s.ok
                      ? "bg-emerald-50 border-emerald-200 text-emerald-700"
                      : "bg-amber-50 border-amber-200 text-amber-700")
                  }
                >
                  <span>{s.ok ? "✓" : "⚠"}</span>
                  {s.text}
                </span>
              ))}
            </div>
          </div>

          {/* ══ Attack Path ══ */}
          <div className="bg-white border border-ink-200 p-5 cx-attack-path">
            <h3 className="text-sm font-extrabold text-ink-800 mb-3 flex items-center gap-1.5">
              <span>🛤️</span> เส้นทางการโจมตี (Attack Path)
            </h3>
            <div className="flex items-stretch gap-1 overflow-x-auto pb-2">
              {data.attack_path.map((n, i) => (
                <div key={i} className="flex items-center gap-1 shrink-0">
                  <div
                    className={
                      "px-3 py-2 rounded-lg border-2 min-w-[110px] text-center " +
                      (NODE_STATUS_CLS[n.status] ?? NODE_STATUS_CLS.normal)
                    }
                  >
                    <div className="text-xs font-bold leading-tight">{n.label}</div>
                    <div className="text-[10px] opacity-80 mt-0.5 leading-tight">{n.sublabel}</div>
                  </div>
                  {i < data.attack_path.length - 1 && (
                    <span className="text-ink-300 text-lg">→</span>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* ══ sections grid ══ */}
          <div className="cx-reference-grid operations">
            {/* ① Entry */}
            <Card title="1. ช่องทางการเข้า (Authentication Entry)" icon="🔑">
              <KV label="Entry Type" value={<Badge tone="brand">{entry.channel_label}</Badge>} />
              <KV label="Source" value={entry.target} />
              <KV label="Endpoint" value={<code className="text-[11px]">{entry.endpoint}</code>} />
              <KV label="Auth Method" value={entry.auth_method} />
              <KV label="Client / App" value={entry.client_app} />
              <KV
                label={entry.scopes_kind === "oauth" ? "Scopes ที่ขอ (OAuth)" : "สิทธิ์ตามบทบาท (RBAC)"}
                value={
                  <div className="flex flex-wrap gap-1 justify-end">
                    {entry.scopes.length
                      ? entry.scopes.map((s) => (
                          <span
                            key={s}
                            className={
                              "px-1.5 py-0.5 rounded text-[10px] " +
                              (entry.scopes_kind === "oauth"
                                ? "bg-emerald-50 text-emerald-700 font-mono"
                                : "bg-violet-50 text-violet-700")
                            }
                          >
                            {s}
                          </span>
                        ))
                      : "—"}
                  </div>
                }
              />
              {entry.role && <KV label="Role" value={<Badge tone="warn">{entry.role}</Badge>} />}
              <div className="border-t border-ink-100 my-2" />
              <KV label="First Seen" value={fmt(entry.first_seen)} mono />
              <KV label="Last Seen" value={fmt(entry.last_seen)} mono />
              <KV label="IP Address" value={entry.ip || "—"} mono />
              <KV
                label="ประเทศ / เมือง"
                value={[entry.geo_country?.toUpperCase(), entry.geo_city].filter(Boolean).join(" / ") || "—"}
              />
              <KV label="Device" value={entry.device_type || "—"} />
              <KV label="Browser" value={entry.browser || "—"} />
              <KV label="Network" value={entry.network} />
            </Card>

            {/* ② Risk Analysis (compact) */}
            <Card title="2. การวิเคราะห์ความเสี่ยง (Risk Analysis)" icon="📊">
              <div className="flex items-center justify-between mb-2">
                <span className="text-3xl font-extrabold text-rose-600 tabular-nums">
                  {risk.score.toFixed(3)}
                </span>
                <Badge tone={lvl.tone}>{risk.level_label}</Badge>
              </div>
              <KV
                label="Decision"
                value={
                  <Badge tone={DECISION_TONE[risk.decision || ""] || "default"}>
                    {(risk.decision || "—").toUpperCase()}
                  </Badge>
                }
              />
              <div className="mt-3">
                <div className="text-[10px] font-bold text-ink-400 uppercase mb-1">Top Reasons</div>
                {risk.top_reasons.length ? (
                  <ul className="space-y-1">
                    {risk.top_reasons.map((r, i) => (
                      <li key={i} className="text-xs font-mono text-ink-700 flex gap-1.5">
                        <span className="text-rose-400">•</span>
                        {r.feature}
                        {r.detail && <span className="text-ink-400"> {r.detail}</span>}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="text-xs text-ink-400">—</div>
                )}
              </div>

              <button
                onClick={() => setShowML((v) => !v)}
                className="mt-3 w-full px-3 py-2 rounded-lg border border-brand-200 bg-brand-50 text-brand-700 text-xs font-semibold hover:bg-brand-100"
              >
                {showML ? "▲ ซ่อน ML Explanation" : "🔬 View ML Explanation (4-Layer + SHAP)"}
              </button>

              {showML && (
                <div className="mt-3 pt-3 border-t border-ink-100">
                  <div className="text-[10px] text-ink-400 mb-2">
                    additive model (Rule + Behavior + IForest) · ไม่ใช่ weighted %
                  </div>
                  {risk.layers.map((l) => (
                    <div key={l.key} className="mb-2">
                      <div className="flex items-baseline justify-between mb-0.5">
                        <span className="text-[11px] font-semibold text-ink-700">{l.label}</span>
                        <span className="text-[11px] font-mono font-bold">
                          {l.value.toFixed(2)}
                          <span className="text-ink-400 font-normal"> / {l.max.toFixed(1)}</span>
                        </span>
                      </div>
                      <div className="h-1.5 bg-ink-100 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-blue-500"
                          style={{ width: `${Math.min((l.value / l.max) * 100, 100)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                  {/* SHAP — ถ้า ML service คืนมา */}
                  {risk.shap && risk.shap.length > 0 ? (
                    <div className="mt-3">
                      <div className="text-[10px] font-bold text-amber-700 uppercase mb-1.5">
                        SHAP (Layer 3 · per-feature)
                      </div>
                      {risk.shap.slice(0, 6).map((s, i) => (
                        <div key={i} className="flex items-baseline justify-between text-[11px] mb-0.5">
                          <span className="text-ink-600 truncate">{s.feature}</span>
                          <span
                            className={`font-mono font-bold ${
                              s.direction === "anomaly" ? "text-rose-600" : "text-emerald-600"
                            }`}
                          >
                            {s.direction === "anomaly" ? "+" : ""}
                            {s.shap.toFixed(3)}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="mt-2 text-[10px] text-ink-400">
                      SHAP ไม่มีสำหรับ session นี้ (ML service ไม่ได้ส่ง explanation)
                    </div>
                  )}
                </div>
              )}
            </Card>

            {/* ③ Reasons (Evidence) */}
            <Card title="3. หลักฐานความเสี่ยง (Evidence · Risk Reasons)" icon="⚠️">
              {reasons.length ? (
                <div className="space-y-2">
                  {reasons.map((r, i) => (
                    <div key={i} className="p-2.5 rounded-lg border border-rose-100 bg-rose-50/40">
                      <div className="text-xs font-bold text-ink-800 font-mono">{r.feature}</div>
                      {r.detail && <div className="text-[11px] text-ink-500 mt-0.5">{r.detail}</div>}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-ink-400">— ไม่มีเหตุผลระบุ —</div>
              )}
            </Card>

            {/* ④ Timeline — 2 แถบ forensic */}
            <Card title="4. ไทม์ไลน์เหตุการณ์ (Timeline)" icon="🕐">
              {timeline.length ? (
                <div className="space-y-4">
                  <TimelineStrand
                    label="🧑‍💻 สิ่งที่บัญชีนี้ทำ"
                    hint="การกระทำสำคัญของบัญชีนี้ (ถ้าเป็นคนร้ายจะเห็นว่าทำอะไร)"
                    events={acctEvents}
                    tone="rose"
                  />
                  <TimelineStrand
                    label="🛡 ระบบ · แอดมินตอบโต้"
                    hint="การตัดสินความเสี่ยง + การจัดการเคสนี้"
                    events={respEvents}
                    tone="brand"
                  />
                </div>
              ) : (
                <div className="text-xs text-ink-400">— ไม่มีเหตุการณ์ที่เกี่ยวข้อง —</div>
              )}
            </Card>

            {/* ⑤ System Response */}
            <Card title="5. การตอบสนองของระบบ (System Response)" icon="⚙️">
              <KV
                label="Decision"
                value={
                  <Badge tone={DECISION_TONE[system_response.decision || ""] || "default"}>
                    {(system_response.decision || "—").toUpperCase()}
                  </Badge>
                }
              />
              <KV label="Action Taken" value={system_response.action_taken} />
              <KV label="Token Issued" value={<YesNo v={system_response.token_issued} />} />
              <KV label="Session Created" value={<YesNo v={system_response.session_created} />} />
              <KV label="Refresh Token" value={<YesNo v={system_response.refresh_issued} />} />
              <KV label="สถานะ session" value={<Badge tone={status.tone}>{status.label}</Badge>} />
              <KV label="Log Saved" value={<YesNo v={system_response.log_saved} yes="✓ บันทึกแล้ว" />} />
              {system_response.shadow_mode && (
                <div className="mt-2 text-[11px] text-amber-600 bg-amber-50 border border-amber-200 rounded-lg p-2">
                  ⚠ Shadow Mode — RBA จับได้แต่ยังไม่ enforce จริง (token ออกปกติ)
                </div>
              )}
            </Card>

            {/* ⑥ Recommended Actions — grouped by category */}
            <Card title="6. แนวทางการจัดการ (Recommended Actions)" icon="🎯">
              <div className="space-y-3">
                {grouped.map((g) => {
                  const meta = ACTION_CATEGORY_META[g.cat];
                  return (
                    <div key={g.cat}>
                      <div className="text-[10px] font-bold text-ink-400 uppercase tracking-wider mb-1.5">
                        {meta.icon} {meta.label}
                      </div>
                      <div className="space-y-1.5">
                        {g.items.map((a) => {
                          const sev = SEVERITY_META[a.severity] ?? SEVERITY_META.info;
                          return (
                            <div
                              key={a.type}
                              className="flex items-center justify-between gap-2 p-2 rounded-lg border border-ink-200 bg-white"
                            >
                              <div className="min-w-0">
                                <div className="text-xs font-bold text-ink-900">{a.title}</div>
                                <div className="text-[10px] text-ink-500">{a.detail}</div>
                              </div>
                              {a.executable ? (
                                <button
                                  onClick={() => runAction(a)}
                                  disabled={!a.enabled || busyType !== null}
                                  className={`shrink-0 px-3 py-1.5 rounded-lg text-white text-xs font-semibold disabled:opacity-40 ${sev.btn}`}
                                >
                                  {busyType === a.type ? "…" : a.button_label}
                                </button>
                              ) : (
                                <Link
                                  href={a.href || "#"}
                                  className="shrink-0 px-3 py-1.5 rounded-lg border border-ink-300 text-ink-700 text-xs font-semibold hover:bg-ink-50"
                                >
                                  {a.button_label}
                                </Link>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
              {msg && (
                <div
                  className={`mt-3 p-2.5 rounded-lg text-xs ${
                    msg.kind === "ok"
                      ? "bg-emerald-50 border border-emerald-200 text-emerald-700"
                      : "bg-rose-50 border border-rose-200 text-rose-700"
                  }`}
                >
                  {msg.text}
                </div>
              )}
            </Card>

            {/* ⑦ Additional Info */}
            <Card title="7. ข้อมูลเพิ่มเติม (Additional Info · 7 วัน)" icon="📈" span={2}>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <Stat label="Incidents (7d)" value={stats_7d.total_incidents} />
                <Stat label="Avg Risk (7d)" value={stats_7d.avg_risk ?? "—"} />
                <Stat label="Blocked (7d)" value={stats_7d.blocked_attempts} />
                <Stat
                  label="Passkey Success"
                  value={stats_7d.passkey_success_rate != null ? `${stats_7d.passkey_success_rate}%` : "—"}
                />
              </div>
            </Card>

            {/* ⑧ Related Links */}
            <Card title="8. ลิงก์ที่เกี่ยวข้อง" icon="🔗">
              <div className="space-y-2">
                {data.related_links.map((l) => (
                  <Link
                    key={l.href}
                    href={l.href}
                    className="flex items-center justify-between px-3 py-2 rounded-lg border border-ink-200 hover:border-brand-400 hover:bg-brand-50 text-sm text-ink-700"
                  >
                    {l.label}
                    <span className="text-ink-400">→</span>
                  </Link>
                ))}
              </div>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── helpers ──

function SummaryCol({
  tone,
  head,
  body,
}: {
  tone: "rose" | "amber" | "emerald";
  head: string;
  body: string;
}) {
  const cls = {
    rose: "border-rose-200 bg-rose-50/50",
    amber: "border-amber-200 bg-amber-50/50",
    emerald: "border-emerald-200 bg-emerald-50/50",
  }[tone];
  return (
    <div className={`rounded-lg border p-3 ${cls}`}>
      <div className="text-[10px] font-bold text-ink-500 uppercase tracking-wider">{head}</div>
      <div className="text-sm font-semibold text-ink-900 mt-1 leading-snug">{body}</div>
    </div>
  );
}

function Card({
  title,
  icon,
  span,
  children,
}: {
  title: string;
  icon: string;
  span?: number;
  children: React.ReactNode;
}) {
  return (
    <article className={`cx-panel cx-reference-card ${span === 2 ? "wide" : ""}`}>
      <header><div><span className="mono">INCIDENT EVIDENCE</span><h2><i>{icon}</i> {title}</h2></div></header>
      <div className="cx-reference-body">{children}</div>
    </article>
  );
}

function KV({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1 text-sm">
      <span className="text-[11px] text-ink-400 font-medium shrink-0 pt-0.5">{label}</span>
      <span className={`text-ink-900 text-right ${mono ? "font-mono text-xs" : ""}`}>{value}</span>
    </div>
  );
}

function YesNo({ v, yes }: { v: boolean; yes?: string }) {
  return v ? (
    <span className="text-emerald-600 font-semibold">{yes || "✓ ใช่"}</span>
  ) : (
    <span className="text-rose-500 font-semibold">✗ ไม่</span>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="p-3 rounded-lg bg-ink-50 border border-ink-100">
      <div className="text-[10px] font-bold text-ink-400 uppercase">{label}</div>
      <div className="text-2xl font-extrabold text-ink-900 tabular-nums mt-0.5">{value}</div>
    </div>
  );
}

function TimelineStrand({
  label,
  hint,
  events,
  tone,
}: {
  label: string;
  hint: string;
  events: TimelineEvent[];
  tone: "rose" | "brand";
}) {
  const dot = tone === "rose" ? "text-rose-400" : "text-brand-400";
  const border = tone === "rose" ? "border-rose-200" : "border-brand-200";
  return (
    <div>
      <div className="text-[11px] font-bold text-ink-600 mb-1">{label}</div>
      {events.length ? (
        <div className={`border-l-2 ${border} pl-3 space-y-1.5`}>
          {events.map((e, i) => (
            <div key={i} className="text-xs">
              <span className="text-ink-400 font-mono">{fmt(e.at, false)}</span>{" "}
              <span className={dot}>•</span>{" "}
              <span className="text-ink-800 font-medium">
                {AUDIT_ACTION_LABEL[e.action] || e.action}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-[11px] text-ink-300 pl-3">{hint} · —</div>
      )}
    </div>
  );
}
