"use client";

type Bucket = { bucket: string; count: number };

type Props = {
  histogram: Bucket[];
};

export function ScoreHistogram({ histogram }: Props) {
  const histMax = Math.max(...histogram.map((b) => b.count), 1);
  const BAR_AREA_PX = 200; // ความสูง bar area (px) — fixed กัน flex-1 collapse

  return (
    <section className="mb-8">
      <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
        Score Distribution · 10 buckets · max={histMax}
      </h3>
      <div className="bg-white rounded-xl border border-ink-200 shadow-sm p-6">
        <div className="flex items-end gap-2">
          {histogram.map((b, i) => {
            const heightPx =
              b.count > 0
                ? Math.max(4, (b.count / histMax) * BAR_AREA_PX)
                : 0;
            const isHigh = i >= 7;
            const isMfa = i >= 4 && i < 7;
            const color = isHigh
              ? "bg-rose-400"
              : isMfa
              ? "bg-amber-400"
              : "bg-emerald-400";
            return (
              <div
                key={b.bucket}
                className="flex-1 flex flex-col items-center gap-2 group"
                title={`${b.bucket}: ${b.count}`}
              >
                <div className="text-[11px] font-mono tabular-nums text-ink-600 font-bold">
                  {b.count}
                </div>
                <div
                  className="w-full flex flex-col justify-end"
                  style={{ height: `${BAR_AREA_PX}px` }}
                >
                  <div
                    className={`w-full rounded-t-md ${color} transition-all duration-500 group-hover:opacity-80`}
                    style={{ height: `${heightPx}px` }}
                  />
                </div>
                <div className="text-[10px] font-mono tabular-nums text-ink-400">
                  {b.bucket}
                </div>
              </div>
            );
          })}
        </div>
        <div className="mt-6 pt-4 border-t border-ink-100 flex justify-between text-[11px] font-semibold text-ink-500">
          <span className="text-emerald-600">&larr; LOW · PASS</span>
          <span className="text-amber-600">MFA ZONE (0.4–0.7)</span>
          <span className="text-rose-600">HIGH · BLOCK &rarr;</span>
        </div>
      </div>
    </section>
  );
}
