"use client";

type Bucket = { bucket: string; count: number };

type Props = {
  histogram: Bucket[];
};

export function ScoreHistogram({ histogram }: Props) {
  const histMax = Math.max(...histogram.map((b) => b.count), 1);

  return (
    <section className="mb-8">
      <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
        Score Distribution · 10 buckets
      </h3>
      <div className="bg-white rounded-xl border border-ink-200 shadow-sm p-6">
        <div className="flex items-end gap-2 h-56">
          {histogram.map((b, i) => {
            const height = (b.count / histMax) * 100;
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
              >
                <div className="text-[11px] font-mono tabular-nums text-ink-600 font-bold">
                  {b.count}
                </div>
                <div className="w-full flex-1 flex items-end">
                  <div
                    className={`w-full rounded-t-md ${color} transition-all duration-500 group-hover:opacity-80`}
                    style={{
                      height: `${Math.max(height, b.count > 0 ? 3 : 0)}%`,
                    }}
                    title={`${b.bucket}: ${b.count}`}
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
