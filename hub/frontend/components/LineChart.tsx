"use client";

/**
 * LineChart — กราฟเส้นพร้อม marker สี่เหลี่ยม (สไตล์สเปรดชีต):
 * gridline แนวนอน + แกน Y ที่มีตัวเลขกำกับ + label แกน X + เส้นเชื่อมจุด
 *
 * ใช้แทนกราฟแท่งเดิมทุกหน้า (ScoreHistogram, Login ต่อวัน ฯลฯ) เพื่อให้
 * รูปแบบกราฟทั้งระบบเป็นชุดเดียวกัน. เป็น SVG ล้วน — ไม่มี dependency
 * ภายนอก, responsive ผ่าน viewBox, และอ่านค่าได้จาก <title> ตอน hover.
 *
 * รองรับหลายเส้น (multi-series) — ใช้แยกเส้นตามระดับความเสี่ยงในหน้า ML.
 * ค่า `null` ใน values = ไม่มีจุดตำแหน่งนั้น (เส้นจะขาดช่วง ไม่ลากข้าม).
 */

export type LineSeries = {
  name: string;
  color: string;
  /** ยาวเท่ากับ labels — null = เว้นช่อง (ไม่วาดจุด/ไม่ลากเส้นผ่าน) */
  values: (number | null)[];
  /**
   * สี marker รายจุด (ยาวเท่ากับ values) — ใช้ตอนอยากให้เส้นเดียว
   * แต่จุดสื่อโซน เช่น histogram ความเสี่ยง เขียว/เหลือง/แดง.
   * ไม่ใส่ = ใช้ `color` ของ series
   */
  pointColors?: (string | undefined)[];
};

type Props = {
  labels: string[];
  series: LineSeries[];
  /** ความสูงพื้นที่วาด (px) */
  height?: number;
  /** แสดงตัวเลขเหนือจุด */
  showValues?: boolean;
  /** จำนวนเส้น gridline แนวนอน (รวมเส้นบนสุด) */
  ticks?: number;
  /** ต่อท้าย tooltip เช่น " logins" */
  valueSuffix?: string;
  /** แสดง legend ด้านบน (ค่า default = แสดงเมื่อมีมากกว่า 1 เส้น) */
  showLegend?: boolean;
  /**
   * แสดง marker สี่เหลี่ยมรายจุด — ปิดเมื่อจุดเยอะ (เช่น latency 288 จุด/24ชม.)
   * ไม่งั้น marker ทับกันจนกลายเป็นแถบทึบ อ่านรูปทรงของเส้นไม่ออก
   */
  showMarkers?: boolean;
  /** ระบายพื้นที่ใต้เส้น (โทนเดียวกับเส้น จาง ๆ) — เหมาะกับกราฟช่วงเวลา */
  area?: boolean;
  /** ความหนาเส้น (ค่า default 2.5 — ลดลงเมื่อจุดถี่) */
  strokeWidth?: number;
};

/** ปัดขึ้นเป็นเลขกลม (1 / 2 / 2.5 / 5 / 10 × 10^k) */
function niceNum(x: number): number {
  if (x <= 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(x)));
  const n = x / mag;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10;
  return step * mag;
}

/**
 * เลือกเพดานแกน Y จาก "ระยะห่าง tick ที่กลม" แทนการปัดค่า max ตรงๆ —
 * ได้ tick เป็นเลขอ่านง่ายและไม่เหลือที่ว่างด้านบนมากเกินไป
 * (เช่น max=68, ticks=5 → step 20 → yMax 80 ไม่ใช่ 100).
 * ถ้าข้อมูลเป็นจำนวนเต็มล้วน (count) บังคับให้ step เป็นจำนวนเต็มด้วย
 */
function axisMax(max: number, ticks: number, allInt: boolean): number {
  if (max <= 0) return allInt ? ticks - 1 : 1;
  let step = niceNum(max / (ticks - 1));
  if (allInt) step = Math.max(1, Math.ceil(step));
  return step * (ticks - 1);
}

/** ตัด values เป็นช่วงที่ต่อเนื่องกัน (ข้าม null) เพื่อไม่ลากเส้นข้ามช่องว่าง */
function segments(values: (number | null)[]): { i: number; v: number }[][] {
  const out: { i: number; v: number }[][] = [];
  let cur: { i: number; v: number }[] = [];
  values.forEach((v, i) => {
    if (v === null || v === undefined) {
      if (cur.length) out.push(cur);
      cur = [];
    } else {
      cur.push({ i, v });
    }
  });
  if (cur.length) out.push(cur);
  return out;
}

export function LineChart({
  labels,
  series,
  height = 220,
  showValues = true,
  ticks = 5,
  valueSuffix = "",
  showLegend,
  showMarkers = true,
  area = false,
  strokeWidth = 2.5,
}: Props) {
  if (labels.length === 0 || series.length === 0) {
    return (
      <div className="text-center text-ink-400 text-sm py-8">ยังไม่มีข้อมูล</div>
    );
  }

  const withLegend = showLegend ?? series.length > 1;

  // ระบบพิกัดภายใน (viewBox) — responsive เองตามความกว้าง container
  const W = 760;
  const H = height;
  const PAD = { top: 18, right: 14, bottom: 34, left: 46 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const allValues = series.flatMap((s) =>
    s.values.filter((v): v is number => v !== null && v !== undefined)
  );
  const rawMax = Math.max(...allValues, 0);
  const allInt = allValues.every((v) => Number.isInteger(v));
  const yMax = axisMax(rawMax, ticks, allInt);

  // จุดเดียว → วางกลาง; หลายจุด → กระจายเต็มความกว้าง
  const x = (i: number) =>
    labels.length === 1
      ? PAD.left + plotW / 2
      : PAD.left + (i / (labels.length - 1)) * plotW;
  const y = (v: number) => PAD.top + plotH - (v / yMax) * plotH;

  const tickVals = Array.from({ length: ticks }, (_, i) => (yMax / (ticks - 1)) * i);

  // label แกน X เยอะเกิน → เว้นระยะกันชนกัน
  const labelEvery = labels.length > 14 ? Math.ceil(labels.length / 12) : 1;

  return (
    <div>
      {withLegend && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 mb-3">
          {series.map((s) => (
            <span key={s.name} className="inline-flex items-center gap-2 text-[11px] font-semibold text-ink-600">
              <span
                className="inline-block w-4 h-[3px] rounded-sm"
                style={{ background: s.color }}
              />
              {s.name}
            </span>
          ))}
        </div>
      )}
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        style={{ height: `${H}px` }}
        role="img"
      >
        {/* gridlines + ตัวเลขแกน Y */}
        {tickVals.map((tv) => (
          <g key={tv}>
            <line
              x1={PAD.left}
              y1={y(tv)}
              x2={W - PAD.right}
              y2={y(tv)}
              stroke="#e2e8f0"
              strokeWidth={1}
            />
            <text
              x={PAD.left - 8}
              y={y(tv) + 3.5}
              textAnchor="end"
              fontSize={10}
              fill="#94a3b8"
              fontFamily="ui-monospace, monospace"
            >
              {yMax >= 1000
                ? `${Math.round(tv / 100) / 10}k`
                : Number.isInteger(tv)
                ? tv
                : tv.toFixed(1)}
            </text>
          </g>
        ))}

        {/* แกน X / แกน Y */}
        <line
          x1={PAD.left}
          y1={PAD.top + plotH}
          x2={W - PAD.right}
          y2={PAD.top + plotH}
          stroke="#cbd5e1"
          strokeWidth={1.5}
        />
        <line
          x1={PAD.left}
          y1={PAD.top}
          x2={PAD.left}
          y2={PAD.top + plotH}
          stroke="#cbd5e1"
          strokeWidth={1.5}
        />

        {/* เส้น + marker ของแต่ละ series */}
        {series.map((s) => (
          <g key={s.name}>
            {/* พื้นที่ใต้เส้น — วาดก่อนเส้นเพื่อให้เส้นทับอยู่ด้านบน */}
            {area &&
              segments(s.values).map((seg, si) =>
                seg.length > 1 ? (
                  <polygon
                    key={`area-${si}`}
                    points={
                      `${x(seg[0].i)},${PAD.top + plotH} ` +
                      seg.map((p) => `${x(p.i)},${y(p.v)}`).join(" ") +
                      ` ${x(seg[seg.length - 1].i)},${PAD.top + plotH}`
                    }
                    fill={s.color}
                    fillOpacity={0.1}
                    stroke="none"
                  />
                ) : null
              )}
            {segments(s.values).map((seg, si) =>
              seg.length > 1 ? (
                <polyline
                  key={`seg-${si}`}
                  points={seg.map((p) => `${x(p.i)},${y(p.v)}`).join(" ")}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={strokeWidth}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              ) : null
            )}
            {showMarkers &&
              s.values.map((v, i) =>
              v === null || v === undefined ? null : (
                <g key={`pt-${i}`}>
                  <rect
                    x={x(i) - 4}
                    y={y(v) - 4}
                    width={8}
                    height={8}
                    fill={s.pointColors?.[i] || s.color}
                    stroke="#fff"
                    strokeWidth={1.5}
                  >
                    <title>{`${s.name} · ${labels[i]}: ${v}${valueSuffix}`}</title>
                  </rect>
                  {showValues && (
                    <text
                      x={x(i)}
                      y={y(v) - 11}
                      textAnchor="middle"
                      fontSize={10.5}
                      fontWeight={700}
                      fill="#334155"
                      fontFamily="ui-monospace, monospace"
                    >
                      {v}
                    </text>
                  )}
                </g>
              )
            )}
          </g>
        ))}

        {/* label แกน X */}
        {labels.map((lb, i) =>
          i % labelEvery === 0 ? (
            <text
              key={`lb-${i}`}
              x={x(i)}
              y={H - 12}
              textAnchor="middle"
              fontSize={10}
              fill="#94a3b8"
              fontFamily="ui-monospace, monospace"
            >
              {lb}
            </text>
          ) : null
        )}
      </svg>
    </div>
  );
}
