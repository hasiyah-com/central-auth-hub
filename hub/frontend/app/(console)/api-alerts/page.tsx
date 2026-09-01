"use client";

import { useEffect, useState, useCallback } from "react";
import { Topbar } from "@/components/Topbar";
import { StatsCard } from "@/components/StatsCard";
import { Badge } from "@/components/Badge";
import { clientFetch } from "@/lib/api";

// ── Types ──

type Alert = {
  id: string;
  rule: string;
  severity: string;
  ip: string | null;
  user_id: string | null;
  detail: Record<string, unknown> | null;
  resolved: boolean;
  created_at: string | null;
};

type AlertsResponse = {
  data: {
    alerts: Alert[];
    total: number;
    rules: Record<string, string>;
  };
};

type ScanResponse = {
  scanned_minutes: number;
  new_alerts: number;
  alerts: Array<{ id: string; rule: string; severity: string; ip: string | null }>;
};

const RULE_ICON: Record<string, string> = {
  excessive_requests: "🔥",
  high_error_rate: "⚠️",
  unauthorized_probing: "🚨",
  bot_pattern: "🤖",
};

const SEVERITY_TONE: Record<string, "warn" | "danger"> = {
  warning: "warn",
  critical: "danger",
};

export default function ApiAlertsPage() {
  const [data, setData] = useState<AlertsResponse["data"] | null>(null);
  const [days, setDays] = useState(7);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanMsg, setScanMsg] = useState<string | null>(null);
  const [filterRule, setFilterRule] = useState<string>("");
  const [filterResolved, setFilterResolved] = useState<string>("");

  const load = useCallback(() => {
    setError(null);
    let url = `/admin/api-alerts?days=${days}`;
    if (filterRule) url += `&rule=${filterRule}`;
    if (filterResolved === "true") url += "&resolved=true";
    if (filterResolved === "false") url += "&resolved=false";
    clientFetch<AlertsResponse>(url)
      .then((res) => setData(res.data))
      .catch((e) => setError(e.detail || "โหลด alerts ไม่สำเร็จ"));
  }, [days, filterRule, filterResolved]);

  useEffect(load, [load]);

  async function handleScan() {
    setScanning(true);
    setScanMsg(null);
    try {
      const res = await clientFetch<ScanResponse>(
        "/admin/api-alerts/scan?minutes=5",
        { method: "POST" }
      );
      setScanMsg(
        res.new_alerts > 0
          ? `พบ ${res.new_alerts} alert ใหม่`
          : "ไม่พบพฤติกรรมผิดปกติ"
      );
      load();
    } catch (e) {
      const err = e as { detail?: string };
      setScanMsg(err.detail || "สแกนไม่สำเร็จ");
    } finally {
      setScanning(false);
    }
  }

  async function handleResolve(id: string) {
    try {
      await clientFetch(`/admin/api-alerts/${id}/resolve`, { method: "POST" });
      load();
    } catch {
      // silent
    }
  }

  const alerts = data?.alerts ?? [];
  const critical = alerts.filter((a) => a.severity === "critical" && !a.resolved).length;
  const warning = alerts.filter((a) => a.severity === "warning" && !a.resolved).length;
  const resolved = alerts.filter((a) => a.resolved).length;

  return (
    <>
      <Topbar title="API Alerts" />
      <main className="signal-page">
        {/* Header */}
        <div className="mb-6 flex items-end justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-sm font-bold text-ink-500 uppercase tracking-wider">
              Rule-Based API Anomaly Detection
            </h2>
            <p className="text-xs text-ink-400 mt-1">
              {/* ตรวจจับพฤติกรรม API ผิดปกติจาก request_logs (OWASP API4:2023 + NIST SP 800-228) */}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={handleScan}
              disabled={scanning}
              className="px-4 py-2 rounded-lg bg-brand-600 text-white text-sm font-semibold hover:bg-brand-700 disabled:opacity-50 transition"
            >
              {scanning ? "กำลังสแกน…" : "สแกนตอนนี้"}
            </button>
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="px-3 py-2 rounded-lg border border-ink-200 bg-white text-sm focus:outline-none focus:border-brand-500"
            >
              <option value={1}>1 วัน</option>
              <option value={7}>7 วัน</option>
              <option value={30}>30 วัน</option>
            </select>
          </div>
        </div>

        {scanMsg && (
          <div className={`mb-4 p-3 rounded-lg text-sm ${
            scanMsg.includes("ไม่พบ") || scanMsg.includes("ไม่สำเร็จ")
              ? "bg-emerald-50 border border-emerald-200 text-emerald-700"
              : "bg-amber-50 border border-amber-200 text-amber-700"
          }`}>
            {scanMsg}
          </div>
        )}

        {error && (
          <div className="mb-6 p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm">
            {error}
          </div>
        )}

        {!data && !error && (
          <div className="text-ink-400 text-sm">กำลังโหลด…</div>
        )}

        {data && (
          <>
            {/* KPI */}
            <section className="mb-8">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <StatsCard
                  label="Critical (ยังไม่ตรวจ)"
                  value={String(critical)}
                  sub="unauthorized probing"
                  icon="🚨"
                  tone={critical > 0 ? "danger" : "good"}
                />
                <StatsCard
                  label="Warning (ยังไม่ตรวจ)"
                  value={String(warning)}
                  sub="excessive requests, errors, bots"
                  icon="⚠️"
                  tone={warning > 0 ? "warn" : "good"}
                />
                <StatsCard
                  label="Resolved"
                  value={String(resolved)}
                  sub="ตรวจสอบแล้ว"
                  icon="✅"
                />
              </div>
            </section>

            {/* Filters */}
            <div className="signal-control-deck mb-4 flex flex-wrap gap-3">
              <select
                value={filterRule}
                onChange={(e) => setFilterRule(e.target.value)}
                className="px-3 py-1.5 rounded-lg border border-ink-200 bg-white text-sm"
              >
                <option value="">ทุกกฎ</option>
                {Object.entries(data.rules).map(([key, desc]) => (
                  <option key={key} value={key}>
                    {RULE_ICON[key] || "📋"} {key}
                  </option>
                ))}
              </select>
              <select
                value={filterResolved}
                onChange={(e) => setFilterResolved(e.target.value)}
                className="px-3 py-1.5 rounded-lg border border-ink-200 bg-white text-sm"
              >
                <option value="">ทั้งหมด</option>
                <option value="false">ยังไม่ตรวจ</option>
                <option value="true">ตรวจแล้ว</option>
              </select>
            </div>

            {/* Alert list */}
            <section>
              <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
                Alerts · {alerts.length} รายการ
              </h3>
              <div className="space-y-3">
                {alerts.length === 0 ? (
                  <div className="bg-white rounded-xl border border-ink-200 p-12 text-center text-ink-400">
                    ไม่มี alert ในช่วงเวลานี้
                  </div>
                ) : (
                  alerts.map((a) => (
                    <AlertCard
                      key={a.id}
                      alert={a}
                      onResolve={() => handleResolve(a.id)}
                    />
                  ))
                )}
              </div>
            </section>

            {/* Rules reference */}
            <section className="mt-8">
              <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
                กฎที่ตรวจจับ (4 กฎ)
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {Object.entries(data.rules).map(([key, desc]) => (
                  <div
                    key={key}
                    className="bg-white rounded-lg border border-ink-200 p-4"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-lg">{RULE_ICON[key] || "📋"}</span>
                      <span className="text-sm font-bold text-ink-900">{key}</span>
                    </div>
                    <p className="text-xs text-ink-500 mt-1">{desc}</p>
                  </div>
                ))}
              </div>
            </section>
          </>
        )}
      </main>
    </>
  );
}

// ── Alert Card ──

function AlertCard({
  alert,
  onResolve,
}: {
  alert: Alert;
  onResolve: () => void;
}) {
  const icon = RULE_ICON[alert.rule] || "📋";
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const detail = (alert.detail || {}) as Record<string, any>;
  const time = alert.created_at
    ? new Date(alert.created_at).toISOString().slice(0, 19).replace("T", " ")
    : "—";

  return (
    <div
      className={`bg-white rounded-xl border shadow-sm p-5 ${
        alert.resolved
          ? "border-ink-200 opacity-60"
          : alert.severity === "critical"
          ? "border-rose-300"
          : "border-amber-300"
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          {/* Header */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-lg">{icon}</span>
            <span className="font-bold text-ink-900">{alert.rule}</span>
            <Badge tone={SEVERITY_TONE[alert.severity] || "warn"}>
              {alert.severity.toUpperCase()}
            </Badge>
            {alert.resolved && <Badge tone="good">RESOLVED</Badge>}
          </div>

          {/* Detail */}
          <div className="mt-2 text-sm text-ink-600">
            {detail.desc && (
              <p>{String(detail.desc)}</p>
            )}
            <div className="mt-1 flex gap-4 flex-wrap text-xs text-ink-500">
              {alert.ip && (
                <span>
                  IP: <span className="font-mono">{alert.ip}</span>
                </span>
              )}
              {detail.count != null && (
                <span>
                  Count: <span className="font-bold">{String(detail.count)}</span>
                  {detail.threshold && ` / threshold ${String(detail.threshold)}`}
                </span>
              )}
              {detail.request_count != null && (
                <span>
                  Requests: <span className="font-bold">{String(detail.request_count)}</span>
                </span>
              )}
              {detail.cv != null && (
                <span>
                  CV: <span className="font-mono">{String(detail.cv)}</span>
                  {` (max ${String(detail.max_cv)})`}
                </span>
              )}
              {detail.mean_interval_sec != null && (
                <span>
                  Interval: <span className="font-mono">{String(detail.mean_interval_sec)}s</span>
                </span>
              )}
              {detail.window_sec != null && (
                <span>Window: {String(detail.window_sec)}s</span>
              )}
            </div>
            {Array.isArray(detail.sample_paths) && detail.sample_paths.length > 0 && (
              <div className="mt-2">
                <span className="text-[10px] font-bold text-ink-400 uppercase">
                  Paths targeted:
                </span>
                <div className="flex flex-wrap gap-1 mt-1">
                  {(detail.sample_paths as string[]).map((p, i) => (
                    <span
                      key={i}
                      className="px-2 py-0.5 rounded bg-ink-100 text-[11px] font-mono text-ink-600"
                    >
                      {p}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Time */}
          <div className="mt-2 text-[11px] font-mono text-ink-400">{time} UTC</div>
        </div>

        {/* Actions */}
        {!alert.resolved && (
          <button
            onClick={onResolve}
            className="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium border border-ink-200 text-ink-600 hover:bg-ink-50 transition"
          >
            Resolve
          </button>
        )}
      </div>
    </div>
  );
}
