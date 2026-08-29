"use client";

import Link from "next/link";
import { Badge } from "@/components/Badge";
import type { Anomaly, UserSession } from "../_types";
import { DECISION_TONE, DEVICE_ICON } from "../_types";

// ── Shared row shape ─────────────────────────────────────
// AnomalyTable สามารถ render ได้ทั้ง Anomaly (overview) และ UserSession (timeline)
// โดยใช้ generic type constraint

type BaseRow = {
  score: number | null;
  decision: string | null;
  ip: string | null;
  geo_country: string | null;
  geo_city: string | null;
  os_name: string | null;
  browser: string | null;
  device_type: string | null;
  is_attack_ip: boolean;
  is_account_takeover: boolean;
  risk_score: number | null;
  risk_breakdown: { rule: number; behavior: number; iforest: number; iforest_raw: number } | null;
  risk_reasons: string[] | null;
  created_at: string;
};

type Props<T extends BaseRow> = {
  rows: T[];
  onRowClick: (row: T) => void;
  emptyMessage?: string;
  /** แสดงคอลัมน์ User (email) — ซ่อนใน user timeline เพราะเป็น user เดียวกัน */
  showUser?: boolean;
  /** render คอลัมน์ feedback badge (เฉพาะ UserSession) */
  showFeedback?: boolean;
  /** render คอลัมน์ ระบบที่ login (เฉพาะ overview Anomaly) */
  showSubsystem?: boolean;
};

// ── Time helpers ─────────────────────────────────────────
// Backend ส่ง naive datetime (เช่น "2026-05-29T11:14:26") — JS new Date()
// ตีความเป็น local time → เพี้ยน 7 ชม. ใน Bangkok browser
// ต้องบังคับ parse เป็น UTC โดย append "Z" ถ้ายังไม่มี timezone
function parseUTC(iso: string): Date {
  const hasTz = /[+-]\d{2}:?\d{2}$|Z$/i.test(iso);
  return new Date(hasTz ? iso : iso + "Z");
}

// เรียง DESC ตามเวลาจริงใน DB (ล่าสุดก่อน) — ไม่ shift เวลา
function prepareRows<T extends BaseRow>(rows: T[]): Array<T & { _displayAt: Date }> {
  return rows
    .map((row) => ({ ...row, _displayAt: parseUTC(row.created_at) }))
    .sort((a, b) => b._displayAt.getTime() - a._displayAt.getTime());
}

function formatBangkok(d: Date): string {
  // DD/MM/YYYY HH:mm:ss — Asia/Bangkok ผ่าน Intl (timezone-safe)
  return d.toLocaleString("th-TH", {
    timeZone: "Asia/Bangkok",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function AnomalyTable<T extends BaseRow>({
  rows,
  onRowClick,
  emptyMessage = "ไม่มีข้อมูล",
  showUser = true,
  showFeedback = false,
  showSubsystem = false,
}: Props<T>) {
  const prepared = prepareRows(rows);
  return (
    <div className="bg-white rounded-xl border border-ink-200 overflow-hidden shadow-sm">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-ink-50">
            <tr>
              {showUser && (
                <th className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider">
                  User
                </th>
              )}
              {showSubsystem && (
                <th className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider w-[160px]">
                  ระบบที่เข้า
                </th>
              )}
              <th className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider w-[140px]">
                Risk Score
              </th>
              <th className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider w-[110px]">
                Decision
              </th>
              <th className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider">
                Device
              </th>
              <th className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider">
                IP / Country
              </th>
              <th className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider w-[120px]">
                Labels
              </th>
              {showFeedback && (
                <th className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider w-[100px]">
                  Feedback
                </th>
              )}
              <th className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider w-[180px]">
                เวลา (Asia/Bangkok)
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-100">
            {prepared.length === 0 ? (
              <tr>
                <td
                  colSpan={(showUser ? 7 : 6) + (showSubsystem ? 1 : 0)}
                  className="px-4 py-12 text-center text-ink-400"
                >
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              prepared.map((row, i) => (
                <tr
                  key={i}
                  onClick={() => onRowClick(row)}
                  className="hover:bg-ink-50/50 transition cursor-pointer"
                >
                  {showUser && (
                    <td className="px-4 py-3 text-ink-700">
                      <UserCell row={row} />
                    </td>
                  )}
                  {showSubsystem && (
                    <td className="px-4 py-3">
                      <SubsystemCell row={row as unknown as Anomaly} />
                    </td>
                  )}
                  <td className="px-4 py-3 text-ink-700">
                    <ScoreCell score={row.risk_score ?? row.score} iforestRaw={row.score} />
                  </td>
                  <td className="px-4 py-3">
                    <Badge tone={DECISION_TONE[row.decision || "unknown"] || "default"}>
                      {(row.decision || "unknown").toUpperCase()}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-ink-700">
                    <DeviceCell row={row} />
                  </td>
                  <td className="px-4 py-3 text-ink-700">
                    <IpCell row={row} />
                  </td>
                  <td className="px-4 py-3">
                    <LabelsCell row={row} />
                  </td>
                  {showFeedback && (
                    <td className="px-4 py-3">
                      <FeedbackCell row={row as unknown as UserSession} />
                    </td>
                  )}
                  <td className="px-4 py-3">
                    <span className="font-mono text-[11px] text-ink-600 whitespace-nowrap">
                      {formatBangkok(row._displayAt)}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Sub-cells ──

function SubsystemCell({ row }: { row: Anomaly }) {
  // subsystem_name = null → Hub-direct (Admin Console / Developer Portal)
  if (!row.subsystem_name) {
    return (
      <div>
        <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-brand-100 text-brand-700 text-xs font-semibold">
          🏛️ ระบบหลัก
        </div>
        <div className="text-[10px] text-ink-400 mt-0.5">Hub-direct</div>
      </div>
    );
  }
  // มี icon ตามชื่อระบบ
  const icon = /หอพัก/i.test(row.subsystem_name)
    ? "🏠"
    : /ห้องสมุด|library/i.test(row.subsystem_name)
    ? "📚"
    : "🧩";
  return (
    <div>
      <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-ink-100 text-ink-800 text-xs font-semibold">
        <span>{icon}</span>
        <span>{row.subsystem_name}</span>
      </div>
      <div className="text-[10px] text-ink-400 mt-0.5">OAuth subsystem</div>
    </div>
  );
}

function UserCell({ row }: { row: BaseRow & Record<string, unknown> }) {
  const anomaly = row as Anomaly;
  const email = anomaly.user_email;
  const userId = anomaly.user_id;
  const sessionId = anomaly.session_id || (row as UserSession).id;
  if (!email) return <span className="text-ink-400">—</span>;
  return (
    <div>
      {userId ? (
        <Link
          href={`/ml/users/${userId}`}
          onClick={(event) => event.stopPropagation()}
          className="font-semibold text-ink-900 underline decoration-ink-300 underline-offset-4 hover:text-brand-700 hover:decoration-brand-500"
        >
          {email}
        </Link>
      ) : (
        <div className="font-semibold text-ink-900">{email}</div>
      )}
      {sessionId && (
        <div className="mt-0.5 font-mono text-[10px] text-ink-400">
          sess {String(sessionId).slice(0, 8)}…
        </div>
      )}
    </div>
  );
}

function ScoreCell({ score, iforestRaw }: { score: number | null; iforestRaw: number | null }) {
  if (score === null) return <span className="text-ink-400">—</span>;
  const pct = Math.round(score * 100);
  const color =
    score >= 0.8 ? "bg-rose-500" : score >= 0.5 ? "bg-amber-500" : score >= 0.3 ? "bg-yellow-400" : "bg-emerald-500";
  return (
    <div>
      <div className="flex items-baseline gap-1">
        <span className="font-mono text-base font-bold text-ink-900 tabular-nums">
          {score.toFixed(3)}
        </span>
        <span className="text-[10px] text-ink-400">risk</span>
      </div>
      <div className="mt-1 h-1.5 w-24 bg-ink-100 rounded-full overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      {iforestRaw != null && iforestRaw !== score && (
        <div className="text-[9px] text-ink-400 mt-0.5 font-mono">
          IF: {iforestRaw.toFixed(2)}
        </div>
      )}
    </div>
  );
}

function DeviceCell({ row }: { row: BaseRow }) {
  const icon = DEVICE_ICON[row.device_type || "unknown"] || DEVICE_ICON.unknown;
  const parts = [row.browser, row.os_name].filter(Boolean);
  return (
    <div className="flex items-center gap-2">
      <span className="text-base">{icon}</span>
      <div className="text-xs text-ink-600">
        {parts.length > 0 ? parts.join(" · ") : "—"}
      </div>
    </div>
  );
}

function IpCell({ row }: { row: BaseRow }) {
  return (
    <div className="font-mono text-xs text-ink-700">
      <div>{row.ip || "—"}</div>
      {row.geo_country && (
        <div className="text-ink-400 text-[10px] uppercase mt-0.5">
          {row.geo_country}
        </div>
      )}
    </div>
  );
}

function LabelsCell({ row }: { row: BaseRow }) {
  const labels: JSX.Element[] = [];
  if (row.is_attack_ip) {
    labels.push(
      <Badge key="atk" tone="danger">
        ATTACK IP
      </Badge>
    );
  }
  if (row.is_account_takeover) {
    labels.push(
      <Badge key="ato" tone="pink">
        TAKEOVER
      </Badge>
    );
  }
  return labels.length > 0 ? (
    <div className="flex flex-wrap gap-1">{labels}</div>
  ) : (
    <span className="text-ink-300">—</span>
  );
}

function FeedbackCell({ row }: { row: UserSession }) {
  if (!row.feedback_label) return <span className="text-ink-300">—</span>;
  const tone =
    row.feedback_label === "true_positive"
      ? "danger"
      : row.feedback_label === "false_positive"
      ? "warn"
      : "good";
  return (
    <Badge tone={tone}>
      {row.feedback_label === "true_positive"
        ? "TP"
        : row.feedback_label === "false_positive"
        ? "FP"
        : "OK"}
    </Badge>
  );
}
