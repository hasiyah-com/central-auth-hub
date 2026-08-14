"use client";

import { LineChart, type LineSeries } from "@/components/LineChart";

type Bucket = { bucket: string; count: number };

type Props = {
  histogram: Bucket[];
};

/** สีของ marker ตามโซนความเสี่ยง (10 buckets = ช่วงละ 0.1) */
function zoneColor(i: number): string {
  if (i >= 7) return "#f43f5e"; // HIGH · BLOCK (0.7–1.0)
  if (i >= 4) return "#f59e0b"; // MFA ZONE (0.4–0.7)
  return "#10b981"; // LOW · PASS (0.0–0.4)
}

export function ScoreHistogram({ histogram }: Props) {
  const histMax = Math.max(...histogram.map((b) => b.count), 1);

  // เส้นเดียว — จุดยังสื่อโซนผ่านสี (pointColors)
  const series: LineSeries[] = [
    {
      name: "Sessions",
      color: "#6366f1",
      values: histogram.map((b) => b.count),
      pointColors: histogram.map((_, i) => zoneColor(i)),
    },
  ];

  return (
    <section className="mb-8">
      <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
        Score Distribution · 10 buckets · max={histMax}
      </h3>
      <div className="bg-white rounded-xl border border-ink-200 shadow-sm p-6">
        <LineChart
          labels={histogram.map((b) => b.bucket)}
          series={series}
          height={240}
          valueSuffix=" sessions"
        />
        <div className="mt-4 pt-4 border-t border-ink-100 flex justify-between text-[11px] font-semibold text-ink-500">
          <span className="text-emerald-600">&larr; LOW · PASS</span>
          <span className="text-amber-600">MFA ZONE (0.4–0.7)</span>
          <span className="text-rose-600">HIGH · BLOCK &rarr;</span>
        </div>
      </div>
    </section>
  );
}
