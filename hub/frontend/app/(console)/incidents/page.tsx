"use client";

/**
 * Incidents — triage list ของ login ที่ RBA flag ว่าเสี่ยง.
 * คลิกแถว → drawer แสดง Incident Summary (Entry→Detected→Impact→Actions).
 */

import { useCallback, useEffect, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { Badge } from "@/components/Badge";
import { StatsCard } from "@/components/StatsCard";
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

  return (
    <>
      <Topbar title="เหตุการณ์เสี่ยง (Incidents)" />
      <main className="p-8 max-w-7xl mx-auto w-full">
        {/* KPIs */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
          <StatsCard label="เหตุการณ์ทั้งหมด" value={kpis?.total ?? "—"} icon="🚨" />
          <StatsCard label="ถูกบล็อก" value={kpis?.blocked ?? "—"} icon="⛔" />
          <StatsCard label="ต้องยืนยันตัวตน" value={kpis?.challenged ?? "—"} icon="🔐" />
          <StatsCard label="Attack IP" value={kpis?.attack_ip ?? "—"} icon="🛑" />
        </div>

        {/* filters */}
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <div className="flex rounded-lg border border-ink-200 overflow-hidden">
            {WINDOW_OPTIONS.map((o) => (
              <button
                key={o.v}
                onClick={() => setHours(o.v)}
                className={
                  "px-3 py-1.5 text-sm font-medium transition " +
                  (hours === o.v
                    ? "bg-brand-600 text-white"
                    : "bg-white text-ink-600 hover:bg-ink-50")
                }
              >
                {o.label}
              </button>
            ))}
          </div>
          <select
            value={decision}
            onChange={(e) => setDecision(e.target.value)}
            className="px-3 py-2 rounded-lg border border-ink-200 bg-white text-sm focus:outline-none focus:border-brand-500"
          >
            <option value="">ทุก decision</option>
            <option value="block">block</option>
            <option value="would_block">would_block</option>
            <option value="challenge">challenge</option>
            <option value="would_mfa">would_mfa</option>
            <option value="mfa_passed">mfa_passed</option>
          </select>
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load()}
            placeholder="ค้นหา email / ชื่อ… (Enter)"
            className="px-3 py-2 rounded-lg border border-ink-200 bg-white text-sm focus:outline-none focus:border-brand-500 w-60"
          />
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm">
            {error}
          </div>
        )}

        {/* list */}
        <div className="bg-white rounded-xl border border-ink-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] font-bold text-ink-400 uppercase tracking-wider border-b border-ink-100">
                <th className="px-4 py-3">เวลา</th>
                <th className="px-4 py-3">ผู้ใช้</th>
                <th className="px-4 py-3">เข้าทาง → เป้าหมาย</th>
                <th className="px-4 py-3">Risk</th>
                <th className="px-4 py-3">Decision</th>
                <th className="px-4 py-3">สถานะ</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-ink-400">
                    กำลังโหลด…
                  </td>
                </tr>
              ) : !data || data.items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-ink-400">
                    ไม่มีเหตุการณ์เสี่ยงในช่วงที่เลือก 🎉
                  </td>
                </tr>
              ) : (
                data.items.map((row) => {
                  const status = STATUS_META[row.status] ?? STATUS_META.expired;
                  return (
                    <tr
                      key={row.id}
                      onClick={() => openDetail(row)}
                      className={
                        "border-b border-ink-50 hover:bg-brand-50/40 cursor-pointer transition " +
                        (openId === row.id ? "bg-brand-50" : "")
                      }
                    >
                      <td className="px-4 py-3 font-mono text-xs text-ink-500 whitespace-nowrap">
                        {row.created_at
                          ? new Date(row.created_at)
                              .toISOString()
                              .slice(5, 16)
                              .replace("T", " ")
                          : "—"}
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-ink-900 truncate max-w-[160px]">
                          {row.full_name || row.user_email || "—"}
                        </div>
                        <div className="text-[11px] text-ink-400 font-mono truncate max-w-[160px]">
                          {row.user_email}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="text-ink-800">{row.channel_label}</div>
                        <div className="text-[11px] text-ink-400">
                          {row.is_subsystem ? "🧩 " : "🏠 "}
                          {row.target}
                        </div>
                      </td>
                      <td className="px-4 py-3 font-mono font-bold tabular-nums">
                        {row.risk_score != null ? row.risk_score.toFixed(2) : "—"}
                      </td>
                      <td className="px-4 py-3">
                        <Badge tone={DECISION_TONE[row.decision || ""] || "default"}>
                          {row.decision || "—"}
                        </Badge>
                      </td>
                      <td className="px-4 py-3">
                        <Badge tone={status.tone}>{status.label}</Badge>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {data && data.total > data.items.length && (
          <p className="mt-3 text-xs text-ink-400 text-center">
            แสดง {data.items.length} จาก {data.total} เหตุการณ์ — กรอง/ลดช่วงเวลาเพื่อดูเจาะจง
          </p>
        )}
      </main>

      {/* full-screen detail modal */}
      {openId !== null && !detailLoading && detail && (
        <IncidentDetailModal
          data={detail}
          onClose={() => setOpenId(null)}
          onActionDone={() => {
            if (openId) fetchDetail(openId);
            load();
          }}
        />
      )}
      {openId !== null && detailLoading && (
        <div className="fixed inset-0 z-50 bg-ink-900/50 grid place-items-center">
          <div className="bg-white rounded-2xl px-6 py-5 shadow-xl text-sm text-ink-500">
            กำลังโหลด…
          </div>
        </div>
      )}
    </>
  );
}
