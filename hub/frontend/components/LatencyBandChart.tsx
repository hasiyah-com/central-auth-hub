"use client";

/**
 * LatencyBandChart — กราฟ response time แบบ band (min–max) + เส้น median
 *
 * ทำไมไม่ใช้ LineChart:
 *  1. LineChart ยึดแกน Y จาก 0 เสมอ — latency ที่ floor ~15,000ms ทำให้ 75%
 *     ของพื้นที่กราฟเป็นช่องว่างใต้เส้น อ่านความแปรผันจริงไม่ออก
 *  2. จุดดิบ 288 จุด/24ชม. แกว่งถี่จนกลายเป็น "ซี่หวี" — เป็น noise ไม่ใช่ signal
 *
 * วิธีแก้: ยุบจุดดิบเป็น bucket ตามเวลา แล้วแสดง
 *   - แถบอ่อน = ช่วง min–max ในแต่ละ bucket (บอกความแกว่ง)
 *   - เส้นทึบ = median (บอกแนวโน้มจริง)
 *   - แกน Y auto-fit ช่วงข้อมูล ไม่บังคับเริ่มที่ 0
 *
 * bucket ที่ ping ไม่สำเร็จทั้งช่วง = เว้นว่าง (ไม่ลากเส้นข้าม) เหมือนเดิม
 */

export type LatencyPoint = { at: string | null; latency_ms: number | null };

type Bucket = {
  i: number;
  min: number;
  max: number;
  med: number;
  label: string;
  n: number;
};

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/** ปัดขึ้น/ลงเป็นเลขกลมตาม step ที่อ่านง่าย */
function niceStep(range: number, want: number): number {
  const raw = range / want;
  const mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  const n = raw / mag;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10;
  return step * mag;
}

function fmt(ms: number): string {
  if (ms >= 1000) {
    const s = ms / 1000;
    return `${s % 1 === 0 ? s : s.toFixed(1)}s`;
  }
  return `${Math.round(ms)}ms`;
}

export function LatencyBandChart({
  points,
  height = 200,
  buckets = 60,
  formatLabel,
}: {
  points: LatencyPoint[];
  height?: number;
  /** จำนวนช่วงเวลาที่ยุบข้อมูลลงมา — 60 ช่วง ≈ 24นาที/ช่วง เมื่อข้อมูล 24ชม. */
  buckets?: number;
  /** แปลง `at` (ISO) เป็นข้อความบนแกน X */
  formatLabel: (at: string) => string;
}) {
  if (points.length === 0) {
    return (
      <div className="text-center text-ink-400 text-sm py-8">ยังไม่มีข้อมูล</div>
    );
  }

  // ── ยุบเป็น bucket ──
  const size = Math.max(1, Math.ceil(points.length / buckets));
  const bs: (Bucket | null)[] = [];
  for (let b = 0; b * size < points.length; b++) {
    const slice = points.slice(b * size, (b + 1) * size);
    const vals = slice
      .map((p) => p.latency_ms)
      .filter((v): v is number => typeof v === "number");
    const firstAt = slice.find((p) => p.at)?.at;
    if (vals.length === 0) {
      bs.push(null); // ping ไม่สำเร็จทั้ง bucket → เว้นช่อง
      continue;
    }
    bs.push({
      i: b,
      min: Math.min(...vals),
      max: Math.max(...vals),
      med: median(vals),
      label: firstAt ? formatLabel(firstAt) : "—",
      n: vals.length,
    });
  }

  const real = bs.filter((b): b is Bucket => b !== null);
  if (real.length === 0) {
    return (
      <div className="text-center text-ink-400 text-sm py-8">
        ยังไม่มีรอบที่ ping สำเร็จ
      </div>
    );
  }

  // ── แกน Y auto-fit (ไม่บังคับเริ่ม 0) ──
  const dataMin = Math.min(...real.map((b) => b.min));
  const dataMax = Math.max(...real.map((b) => b.max));
  const span = Math.max(dataMax - dataMin, Math.max(dataMax * 0.05, 1));
  const step = niceStep(span * 1.25, 4);
  const yMin = Math.max(0, Math.floor((dataMin - span * 0.15) / step) * step);
  const yMax = Math.ceil((dataMax + span * 0.15) / step) * step;

  const W = 760;
  const H = height;
  const PAD = { top: 12, right: 12, bottom: 26, left: 52 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const n = bs.length;
  const x = (i: number) => PAD.left + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const y = (v: number) =>
    PAD.top + plotH - ((v - yMin) / (yMax - yMin || 1)) * plotH;

  const yTicks: number[] = [];
  for (let v = yMin; v <= yMax + 1e-6; v += step) yTicks.push(v);

  // ── ตัดเป็นช่วงต่อเนื่อง (ข้าม bucket ที่ว่าง) ──
  const segs: Bucket[][] = [];
  let cur: Bucket[] = [];
  bs.forEach((b) => {
    if (b === null) {
      if (cur.length) segs.push(cur);
      cur = [];
    } else cur.push(b);
  });
  if (cur.length) segs.push(cur);

  const labelEvery = Math.max(1, Math.ceil(n / 8));

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }}>
      {/* gridline + ค่าแกน Y */}
      {yTicks.map((v) => (
        <g key={`t-${v}`}>
          <line
            x1={PAD.left}
            y1={y(v)}
            x2={W - PAD.right}
            y2={y(v)}
            stroke="#eef1f5"
            strokeWidth={1}
          />
          <text
            x={PAD.left - 7}
            y={y(v) + 3}
            textAnchor="end"
            fontSize={9}
            fill="#9aa5b1"
            fontFamily="ui-monospace, monospace"
          >
            {fmt(v)}
          </text>
        </g>
      ))}

      {/* แถบ min–max ต่อช่วง */}
      {segs.map((seg, si) => (
        <polygon
          key={`band-${si}`}
          points={
            seg.map((b) => `${x(b.i)},${y(b.max)}`).join(" ") +
            " " +
            [...seg].reverse().map((b) => `${x(b.i)},${y(b.min)}`).join(" ")
          }
          fill="#0ea5e9"
          fillOpacity={0.16}
          stroke="none"
        />
      ))}

      {/* เส้น median */}
      {segs.map((seg, si) =>
        seg.length > 1 ? (
          <polyline
            key={`med-${si}`}
            points={seg.map((b) => `${x(b.i)},${y(b.med)}`).join(" ")}
            fill="none"
            stroke="#0284c7"
            strokeWidth={1.8}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ) : (
          <circle
            key={`med-${si}`}
            cx={x(seg[0].i)}
            cy={y(seg[0].med)}
            r={2}
            fill="#0284c7"
          />
        )
      )}

      {/* พื้นที่ hover อ่านค่าราย bucket */}
      {real.map((b) => (
        <rect
          key={`hit-${b.i}`}
          x={x(b.i) - plotW / n / 2}
          y={PAD.top}
          width={plotW / n}
          height={plotH}
          fill="transparent"
        >
          <title>{`${b.label} · median ${fmt(b.med)} (${fmt(b.min)}–${fmt(
            b.max
          )}, ${b.n} รอบ)`}</title>
        </rect>
      ))}

      {/* label แกน X */}
      {bs.map((b, i) =>
        b && i % labelEvery === 0 ? (
          <text
            key={`x-${i}`}
            x={x(i)}
            y={H - 8}
            textAnchor="middle"
            fontSize={9}
            fill="#9aa5b1"
            fontFamily="ui-monospace, monospace"
          >
            {b.label}
          </text>
        ) : null
      )}
    </svg>
  );
}
