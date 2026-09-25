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

const SERIES = [
  { key: "low" as const, label: "ต่ำ", color: "#10b981" },
  { key: "medium" as const, label: "ปานกลาง", color: "#f59e0b" },
  { key: "high" as const, label: "สูง", color: "#f43f5e" },
];

function dateKey(date: Date) {
  return date.toISOString().slice(0, 10);
}

export function RiskDailyBarChart({ daily, days, rangeEnd }: Props) {
  const safeDays = Math.max(1, Math.min(days, 31));
  const byDate = new Map(daily.map((item) => [item.date.slice(0, 10), item]));
  const parsedEnd = new Date(
    /[+-]\\d{2}:?\\d{2}$|Z$/i.test(rangeEnd) ? rangeEnd : rangeEnd + "Z"
  );
  const end = Number.isFinite(parsedEnd.getTime()) ? parsedEnd : new Date();
  const points = Array.from({ length: safeDays }, (_, index) => {
    const date = new Date(end);
    date.setUTCDate(end.getUTCDate() - (safeDays - 1 - index));
    const key = dateKey(date);
    const item = byDate.get(key);
    return {
      date: key,
      label: key.slice(5),
      count: item?.count ?? 0,
      low: item?.low ?? 0,
      medium: item?.medium ?? 0,
      high: item?.high ?? 0,
      unknown: item?.unknown ?? 0,
    };
  });

  const showUnknown = points.some((point) => point.unknown > 0);
  const series = showUnknown
    ? [...SERIES, { key: "unknown" as const, label: "ยังไม่ประเมิน", color: "#94a3b8" }]
    : SERIES;
  const rawMax = Math.max(
    1,
    ...points.flatMap((point) => series.map((item) => point[item.key]))
  );
  const step = Math.max(1, Math.ceil(rawMax / 4));
  const yMax = step * 4;
  const W = 860;
  const H = 250;
  const pad = { left: 42, right: 12, top: 14, bottom: 36 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;
  const groupW = plotW / points.length;
  const gap = 3;
  const barW = Math.min(22, Math.max(5, (groupW * 0.72 - gap * (series.length - 1)) / series.length));
  const barsW = barW * series.length + gap * (series.length - 1);
  const y = (value: number) => pad.top + plotH - (value / yMax) * plotH;
  const total = points.reduce((sum, point) => sum + point.count, 0);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          {series.map((item) => (
            <span
              key={item.key}
              className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-ink-600"
            >
              <i
                className="inline-block h-2.5 w-2.5 rounded-[2px]"
                style={{ background: item.color }}
              />
              {item.label}
            </span>
          ))}
        </div>
        <span className="font-mono text-[11px] text-ink-400">
          รวม {total.toLocaleString("th-TH")} ครั้ง
        </span>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="block w-full"
        role="img"
        aria-label={`กราฟ Login รายวันแยกตามระดับความเสี่ยง ${safeDays} วัน`}
      >
        {[0, 1, 2, 3, 4].map((index) => {
          const value = index * step;
          const lineY = y(value);
          return (
            <g key={index}>
              <line
                x1={pad.left}
                x2={W - pad.right}
                y1={lineY}
                y2={lineY}
                stroke={index === 0 ? "#cbd5e1" : "#e8eef3"}
              />
              <text
                x={pad.left - 8}
                y={lineY + 4}
                textAnchor="end"
                fontSize={10}
                fill="#94a3b8"
                fontFamily="ui-monospace, monospace"
              >
                {value}
              </text>
            </g>
          );
        })}

        {points.map((point, pointIndex) => {
          const center = pad.left + pointIndex * groupW + groupW / 2;
          const startX = center - barsW / 2;
          return (
            <g key={point.date}>
              {series.map((item, seriesIndex) => {
                const value = point[item.key];
                const top = y(value);
                const height = Math.max(0, pad.top + plotH - top);
                return (
                  <rect
                    key={item.key}
                    x={startX + seriesIndex * (barW + gap)}
                    y={top}
                    width={barW}
                    height={height}
                    rx={2}
                    fill={item.color}
                  >
                    <title>{`${point.date} · ${item.label}: ${value} ครั้ง`}</title>
                  </rect>
                );
              })}
              <text
                x={center}
                y={H - 12}
                textAnchor="middle"
                fontSize={10}
                fill="#718096"
                fontFamily="ui-monospace, monospace"
              >
                {point.label}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-ink-400">
        <span>ต่ำ: คะแนน &lt; 0.40</span>
        <span>ปานกลาง: 0.40–0.49</span>
        <span>สูง: ≥ 0.50</span>
      </div>
    </div>
  );
}
