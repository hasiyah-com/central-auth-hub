"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { StatsCard } from "@/components/StatsCard";
import { Badge } from "@/components/Badge";
import { SlidePanel } from "@/components/SlidePanel";
import { clientFetch } from "@/lib/api";
import { AnomalyTable } from "../../_components/AnomalyTable";
import { SessionDetailPanel } from "../../_components/SessionDetailPanel";
import type { UserTimeline, UserSession } from "../../_types";

const USER_TYPE_TONE: Record<string, "good" | "warn" | "danger" | "brand" | "default"> = {
  admin: "danger",
  staff: "brand",
  teacher: "warn",
  student: "good",
};

export default function UserTimelinePage({
  params,
}: {
  params: { id: string };
}) {
  const userId = params.id;
  const [data, setData] = useState<UserTimeline["data"] | null>(null);
  const [days, setDays] = useState(30);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<UserSession | null>(null);

  const load = useCallback(() => {
    setError(null);
    clientFetch<UserTimeline>(
      `/admin/ml/users/${userId}/sessions?days=${days}&limit=100`
    )
      .then((res) => setData(res.data))
      .catch((e) => setError(e.detail || "โหลดข้อมูล user ไม่สำเร็จ"));
  }, [userId, days]);

  useEffect(load, [load]);

  const fmt = (n: number) => n.toLocaleString("en-US");
  const sessions = data?.sessions ?? [];
  const avgScore =
    sessions.length > 0
      ? sessions.reduce((sum, s) => sum + (s.score ?? 0), 0) / sessions.length
      : 0;
  const flagged = sessions.filter((s) => (s.score ?? 0) >= 0.4).length;

  return (
    <>
      <Topbar title={data ? `ประวัติ ML · ${data.user.full_name}` : "ประวัติ ML"} />
      <main className="p-8 max-w-7xl mx-auto w-full">
        {/* Breadcrumb */}
        <Link
          href="/ml"
          className="text-xs text-ink-500 hover:text-brand-600 underline"
        >
          &larr; ML Overview
        </Link>

        {error && (
          <div className="mt-4 p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm">
            {error}
          </div>
        )}

        {!data && !error && (
          <div className="mt-4 text-ink-400 text-sm">กำลังโหลด…</div>
        )}

        {data && (
          <>
            {/* Hero */}
            <div className="mt-3 mb-6 flex items-end justify-between gap-4 flex-wrap">
              <div>
                <h2 className="text-2xl font-extrabold text-ink-900">
                  {data.user.full_name}
                </h2>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-sm text-ink-500">{data.user.email}</span>
                  <Badge tone={USER_TYPE_TONE[data.user.user_type] || "default"}>
                    {data.user.user_type.toUpperCase()}
                  </Badge>
                </div>
              </div>
              <select
                value={days}
                onChange={(e) => setDays(Number(e.target.value))}
                className="px-3 py-2 rounded-lg border border-ink-200 bg-white text-sm focus:outline-none focus:border-brand-500"
              >
                <option value={7}>7 วัน</option>
                <option value={30}>30 วัน</option>
                <option value={90}>90 วัน</option>
                <option value={365}>1 ปี</option>
              </select>
            </div>

            {/* KPI mini x3 */}
            <section className="mb-8">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <StatsCard
                  label="Total Sessions"
                  value={fmt(sessions.length)}
                  sub={`${days} วันล่าสุด`}
                  icon="🔑"
                />
                <StatsCard
                  label="Avg Score"
                  value={avgScore.toFixed(3)}
                  sub="ค่าเฉลี่ย anomaly score"
                  icon="📊"
                  tone={avgScore >= 0.4 ? "warn" : "default"}
                />
                <StatsCard
                  label="Flagged"
                  value={fmt(flagged)}
                  sub="score >= 0.4"
                  icon="⚠️"
                  tone={flagged > 0 ? "danger" : "good"}
                />
              </div>
            </section>

            {/* Session table */}
            <section>
              <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
                Sessions · {sessions.length} รายการ
              </h3>
              <AnomalyTable
                rows={sessions}
                onRowClick={setSelected}
                showUser={false}
                showFeedback={true}
                emptyMessage="ไม่มี session ในช่วงเวลานี้"
              />
            </section>
          </>
        )}
      </main>

      {/* Slide panel */}
      <SlidePanel
        open={!!selected}
        onClose={() => setSelected(null)}
        title="Session Detail"
      >
        {selected && (
          <SessionDetailPanel
            session={selected}
            onFeedbackSaved={() => {
              load();
              setSelected(null);
            }}
            hideUserLink
          />
        )}
      </SlidePanel>
    </>
  );
}
