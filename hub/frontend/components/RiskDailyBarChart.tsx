"use client";

type DailyRisk = {
  date: string;
  count: number;
  low: number;
  medium: number;
  high: number;
  unknown: number;
};

type Props = {
  daily: DailyRisk[];
  days: number;
  rangeEnd: string;
};

const LEVELS = [
  { key: "low" as const, label: "ต่ำ", hint: "< 0.40", color: "#10b981", track: "bg-emerald-500" },
  { key: "medium" as const, label: "ปานกลาง", hint: "0.40–0.49", color: "#f59e0b", track: "bg-amber-500" },
  { key: "high" as const, label: "สูง", hint: "≥ 0.50", color: "#f43f5e", track: "bg-rose-500" },
];

function dateKey(date: Date) {
  return date.toISOString().slice(0, 10);
}

function formatDate(value: string) {
  const date = new Date(value + "T00:00:00+07:00");
  return new Intl.DateTimeFormat("th-TH", {
    day: "2-digit",
    month: "short",
  }).format(date);
}

export function RiskDailyBarChart({ daily, days, rangeEnd }: Props) {
  const safeDays = Math.max(1, Math.min(days, 31));
  const byDate = new Map(daily.map((item) => [item.date.slice(0, 10), item]));
  // Backend ส่งช่วงวันที่ตาม Asia/Bangkok; ใช้ส่วนวันที่โดยตรงเพื่อไม่ให้
  // การแปลงเป็น UTC เลื่อนวันย้อนหลังในช่วงก่อน 07:00 น.
  const endKey = /^\d{4}-\d{2}-\d{2}/.exec(rangeEnd)?.[0];
  const parsedEnd = new Date(`${endKey ?? dateKey(new Date())}T00:00:00Z`);
  const end = Number.isFinite(parsedEnd.getTime()) ? parsedEnd : new Date();
  const points = Array.from({ length: safeDays }, (_, index) => {
    const date = new Date(end);
    date.setUTCDate(end.getUTCDate() - (safeDays - 1 - index));
    const key = dateKey(date);
    const item = byDate.get(key);
    return {
      date: key,
      count: item?.count ?? 0,
      low: item?.low ?? 0,
      medium: item?.medium ?? 0,
      high: item?.high ?? 0,
      unknown: item?.unknown ?? 0,
    };
  });

  const totals = points.reduce(
    (sum, point) => ({
      low: sum.low + point.low,
      medium: sum.medium + point.medium,
      high: sum.high + point.high,
      unknown: sum.unknown + point.unknown,
      count: sum.count + point.count,
    }),
    { low: 0, medium: 0, high: 0, unknown: 0, count: 0 }
  );
  const classifiedTotal = totals.low + totals.medium + totals.high + totals.unknown;
  const denominator = Math.max(1, classifiedTotal);
  const hasUnknown = totals.unknown > 0;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
      <div className="overflow-hidden rounded-xl border border-ink-200 bg-white">
        <div className="grid grid-cols-[minmax(104px,1.25fr)_repeat(4,minmax(48px,.62fr))] border-b border-ink-200 bg-ink-50 px-3 py-2 text-[10px] font-bold uppercase tracking-[0.08em] text-ink-500">
          <span>วันที่</span>
          <span className="text-right text-emerald-700">ต่ำ</span>
          <span className="text-right text-amber-700">กลาง</span>
          <span className="text-right text-rose-700">สูง</span>
          <span className="text-right">รวม</span>
        </div>
        <div className="divide-y divide-ink-100">
          {points.map((point) => {
            const isRiskDay = point.high > 0;
            return (
              <div
                key={point.date}
                className={`grid grid-cols-[minmax(104px,1.25fr)_repeat(4,minmax(48px,.62fr)) items-center px-3 py-2 text-[12px] ${
                  isRiskDay ? "bg-rose-50/55" : "bg-white"
                }`}
              >
                <span className="flex min-w-0 items-center gap-2 font-semibold text-ink-700">
                  <i className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    isRiskDay ? "bg-rose-500" : point.count > 0 ? "bg-cyan-500" : "bg-ink-200"
                  }`} />
                  <span className="truncate">{formatDate(point.date)}</span>
                </span>
                <span className="text-right font-mono font-semibold text-emerald-700">{point.low}</span>
                <span className="text-right font-mono font-semibold text-amber-700">{point.medium}</span>
                <span className="text-right font-mono font-semibold text-rose-700">{point.high}</span>
                <span className="text-right font-mono font-bold text-ink-800">{point.count}</span>
              </div>
            );
          })}
        </div>
      </div>

      <aside className="rounded-xl border border-ink-200 bg-gradient-to-b from-ink-50 to-white p-4">
        <div className="flex items-start justify-between gap-3 border-b border-ink-200 pb-3">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-cyan-700">
              Severity mix
            </p>
            <p className="mt-1 text-sm font-bold text-ink-800">สัดส่วนความเสี่ยง</p>
          </div>
          <div className="text-right">
            <p className="font-mono text-2xl font-black leading-none text-ink-900">
              {totals.count.toLocaleString("th-TH")}
            </p>
            <p className="mt-1 text-[10px] text-ink-400">ครั้ง</p>
          </div>
        </div>

        <div className="mt-4 flex h-3 overflow-hidden rounded-full bg-ink-100" aria-label="สัดส่วนระดับความเสี่ยง">
          {LEVELS.map((level) => {
            const value = totals[level.key];
            return value > 0 ? (
              <span
                key={level.key}
                style={{ width: `${(value / denominator) * 100}%`, backgroundColor: level.color }}
                title={`${level.label} ${value} ครั้ง`}
              />
            ) : null;
          })}
          {hasUnknown ? (
            <span
              className="bg-slate-400"
              style={{ width: `${(totals.unknown / denominator) * 100}%` }}
              title={`ยังไม่ประเมิน ${totals.unknown} ครั้ง`}
            />
          ) : null}
        </div>

        <div className="mt-4 space-y-2.5">
          {LEVELS.map((level) => {
            const value = totals[level.key];
            return (
              <div key={level.key} className="grid grid-cols-[1fr_auto] items-center gap-3">
                <div className="min-w-0">
                  <div className="flex items-center justify-between gap-2 text-[11px]">
                    <span className="inline-flex items-center gap-1.5 font-semibold text-ink-700">
                      <i className="h-2 w-2 rounded-[2px]" style={{ backgroundColor: level.color }} />
                      {level.label}
                    </span>
                    <span className="text-[10px] text-ink-400">{level.hint}</span>
                  </div>
                  <div className="mt-1 h-1 overflow-hidden rounded-full bg-ink-100">
                    <div
                      className={`h-full rounded-full ${level.track}`}
                      style={{ width: `${(value / denominator) * 100}%` }}
                    />
                  </div>
                </div>
                <span className="w-7 text-right font-mono text-sm font-bold text-ink-800">{value}</span>
              </div>
            );
          })}
          {hasUnknown ? (
            <div className="flex items-center justify-between border-t border-ink-200 pt-2 text-[11px]">
              <span className="font-semibold text-ink-500">ยังไม่ประเมิน</span>
              <span className="font-mono font-bold text-ink-700">{totals.unknown}</span>
            </div>
          ) : null}
        </div>

        {totals.count !== classifiedTotal ? (
          <p className="mt-3 rounded-lg bg-amber-50 px-2.5 py-2 text-[10px] leading-relaxed text-amber-800">
            จำนวนรวมไม่ตรงกับผลจำแนก กรุณาตรวจข้อมูลต้นทาง
          </p>
        ) : (
          <p className="mt-3 text-[10px] leading-relaxed text-ink-400">
            ผลรวมตรวจสอบแล้วตรงกับข้อมูลรายวัน
          </p>
        )}
      </aside>
    </div>
  );
}
