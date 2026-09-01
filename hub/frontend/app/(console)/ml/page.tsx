"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { StatsCard } from "@/components/StatsCard";
import { Badge } from "@/components/Badge";
import { SlidePanel } from "@/components/SlidePanel";
import { clientFetch } from "@/lib/api";
import { ScoreHistogram } from "./_components/ScoreHistogram";
import { AnomalyTable } from "./_components/AnomalyTable";
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

  return (
    <>
      <Topbar title="ML / ความผิดปกติ" />
      <main className="signal-page">
        {/* Header + window selector */}
        <div className="mb-6 flex items-end justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-sm font-bold text-ink-500 uppercase tracking-wider">
              HYBRID 4 Layer · Anomaly Detection
            </h2>
            <p className="text-xs text-ink-400 mt-1">
              {/* ทุก login session ผ่าน ML scoring (12 features, Shadow Mode) */}
              {ov && (
                <>
                  {" "}· window {ov.data.range.from.slice(0, 10)} →{" "}
                  {ov.data.range.to.slice(0, 10)}
                </>
              )}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {ov && (
              <Badge tone={ov.meta.shadow_mode ? "warn" : "danger"}>
                {ov.meta.shadow_mode ? "◐ SHADOW MODE" : "● ENFORCING"}
              </Badge>
            )}
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="px-3 py-2 rounded-lg border border-ink-200 bg-white text-sm focus:outline-none focus:border-brand-500"
            >
              <option value={1}>1 วันล่าสุด</option>
              <option value={7}>7 วันล่าสุด</option>
              <option value={30}>30 วันล่าสุด</option>
              <option value={90}>90 วันล่าสุด</option>
            </select>
          </div>
        </div>

        {error && (
          <div className="mb-6 p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm">
            {error}
          </div>
        )}

        {!ov && !error && (
          <div className="text-ink-400 text-sm">กำลังโหลด…</div>
        )}

        {ov && (
          <>
            {/* KPI cards */}
            <section className="mb-8">
              <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
                ภาพรวม
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <StatsCard
                  label="Login ทั้งหมด"
                  value={fmt(total)}
                  sub="sessions scored"
                  icon="🔑"
                />
                <StatsCard
                  label="Anomaly Rate"
                  value={`${anomalyRate}%`}
                  sub={`${anomalyCount} / ${total}`}
                  icon="📈"
                  tone={Number(anomalyRate) > 5 ? "danger" : "default"}
                />
                <StatsCard
                  label="MFA / would_mfa"
                  value={fmt((dec.mfa ?? 0) + (dec.would_mfa ?? 0))}
                  sub={`live ${dec.mfa ?? 0} · shadow ${dec.would_mfa ?? 0}`}
                  icon="🛡️"
                  tone="warn"
                />
                <StatsCard
                  label="Block / would_block"
                  value={fmt((dec.block ?? 0) + (dec.would_block ?? 0))}
                  sub={`live ${dec.block ?? 0} · shadow ${dec.would_block ?? 0}`}
                  icon="🚫"
                  tone="danger"
                />
              </div>
            </section>

            {/* Histogram */}
            <ScoreHistogram histogram={ov.data.score_histogram} />

            {/* Link card → Threshold Tuning */}
            <section className="mb-8">
              <Link
                href="/ml/threshold"
                className="block bg-white rounded-xl border border-ink-200 shadow-sm p-5 hover:border-brand-400 hover:shadow-md transition group"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider">
                      Threshold Tuning
                    </h3>
                    <p className="text-sm text-ink-600 mt-1">
                      Block ={" "}
                      <span className="font-mono font-bold text-rose-600">
                        {ov.meta.thresholds.block}
                      </span>
                      {" · "}MFA ={" "}
                      <span className="font-mono font-bold text-amber-600">
                        {ov.meta.thresholds.mfa}
                      </span>
                    </p>
                  </div>
                  <span className="text-ink-400 group-hover:text-brand-600 text-lg transition">
                    &rarr;
                  </span>
                </div>
              </Link>
            </section>

            {/* Sessions table — toggle Top Anomalies / Recent Sessions */}
            <section>
              <div className="flex items-center justify-between mb-3 flex-wrap gap-3">
                <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider">
                  {sortMode === "score"
                    ? "Top Anomalies"
                    : "Recent Sessions"}{" "}
                  · {ov.data.top_anomalies.length} sessions
                </h3>
                <div className="inline-flex rounded-lg border border-ink-200 bg-white overflow-hidden text-xs font-semibold">
                  <button
                    onClick={() => setSortMode("recent")}
                    className={
                      "px-3 py-1.5 transition " +
                      (sortMode === "recent"
                        ? "bg-brand-600 text-white"
                        : "text-ink-600 hover:bg-ink-50")
                    }
                  >
                    🕒 Recent
                  </button>
                  <button
                    onClick={() => setSortMode("score")}
                    className={
                      "px-3 py-1.5 transition border-l border-ink-200 " +
                      (sortMode === "score"
                        ? "bg-brand-600 text-white"
                        : "text-ink-600 hover:bg-ink-50")
                    }
                  >
                    🔥 Top Score
                  </button>
                </div>
              </div>
              <p className="text-[11px] text-ink-400 mb-2">
                {sortMode === "score"
                  ? "เรียงตาม anomaly score สูง→ต่ำ"
                  : "เรียงตามเวลาล่าสุด"}
              </p>
              <AnomalyTable
                rows={ov.data.top_anomalies}
                onRowClick={setSelected}
                emptyMessage={
                  sortMode === "score"
                    ? "ไม่มี anomaly ใน window นี้"
                    : "ไม่มี session ใน window นี้"
                }
                showSubsystem
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
          />
        )}
      </SlidePanel>
    </>
  );
}
