"use client";

/**
 * Auth Topology Globe — ลูกโลก 3D (amCharts 5, orthographic) แบบ Sankey-map.
 *  - หมุน/ลากได้ เริ่มต้นหันมาที่ประเทศไทย ไฮไลต์ TH
 *  - Hub ปักหมุดที่ตั้งจริง: ม.นราธิวาสราชนครินทร์ จ.นราธิวาส (6.43N, 101.82E)
 *  - เส้นผู้ใช้ → Hub โค้ง geodesic + จุดวิ่งตามเส้น สีตามระดับความเสี่ยง
 *    (เขียว <0.40 · เหลือง 0.40–0.49 · แดง ≥0.50 จาก risk_score จริง)
 *  - ระบบย่อยรอบวิทยาเขต เชื่อม Hub ด้วยเส้นสีน้ำเงิน จุดสีตาม health
 * โหลด amCharts แบบ dynamic ใน useEffect (กัน SSR พัง)
 */

import { useEffect, useRef } from "react";

type GeoEntry = { country: string; risk: "green" | "yellow" | "red"; count: number };
type SubNode = {
  id: string;
  name: string;
  status: string;
  health: string | null;
  latency_ms: number | null;
};

// ── ที่ตั้ง Hub จริง: ม.นราธิวาสราชนครินทร์ ──
const HUB_LON = 101.82;
const HUB_LAT = 6.43;

const CENTROID: Record<string, [number, number]> = {
  // [lat, lon]
  TH: [15.5, 101.0], US: [39, -98], JP: [36, 138], GB: [54, -2], SG: [1.35, 103.8],
  AU: [-25, 133], CN: [35, 105], IN: [21, 78], DE: [51, 10], FR: [46, 2],
  MY: [4, 102], KR: [36.5, 128], RU: [58, 60], BR: [-14, -51], CA: [56, -106],
  VN: [16, 107], ID: [-2, 113], PH: [12, 122], KH: [12.5, 105], LA: [18, 103.8],
  MM: [21, 96], AE: [24, 54], SA: [24, 45], EG: [26, 30], NG: [9, 8],
  ZA: [-29, 24], NL: [52, 5.5], IT: [42, 12.5], ES: [40, -4], SE: [62, 15],
  TR: [39, 35], PK: [30, 69], BD: [24, 90], NZ: [-42, 172], MX: [23, -102],
  AR: [-34, -64], UA: [49, 32], PL: [52, 19], TW: [23.7, 121], HK: [22.3, 114.2],
};

const RISK_HEX: Record<string, number> = {
  green: 0x34d399,
  yellow: 0xfbbf24,
  red: 0xfb7185,
};
const HEALTH_HEX: Record<string, number> = {
  online: 0x34d399,
  degraded: 0xfbbf24,
  down: 0xfb7185,
};
const BLUE = 0x3b82f6;

export function AuthTopologyMap({
  geo,
  subsystems,
}: {
  geo: GeoEntry[];
  subsystems: SubNode[];
}) {
  const chartRef = useRef<HTMLDivElement>(null);
  // เก็บ data ล่าสุดไว้ใน ref — สร้าง chart ครั้งเดียว ไม่ rebuild ทุก refresh 30s
  const dataRef = useRef({ geo, subsystems });
  dataRef.current = { geo, subsystems };

  useEffect(() => {
    let disposed = false;
    let rootObj: { dispose(): void } | null = null;

    (async () => {
      const [am5, am5map, worldLowMod, animatedMod] = await Promise.all([
        import("@amcharts/amcharts5"),
        import("@amcharts/amcharts5/map"),
        import("@amcharts/amcharts5-geodata/worldLow"),
        import("@amcharts/amcharts5/themes/Animated"),
      ]);
      if (disposed || !chartRef.current) return;
      const worldLow = worldLowMod.default;
      const am5themes_Animated = animatedMod.default;
      const { geo: geoData, subsystems: subsData } = dataRef.current;

      const root = am5.Root.new(chartRef.current);
      rootObj = root;
      root.setThemes([am5themes_Animated.new(root)]);

      const chart = root.container.children.push(
        am5map.MapChart.new(root, {
          panX: "rotateX",
          panY: "rotateY",
          projection: am5map.geoOrthographic(),
          paddingTop: 12,
          paddingBottom: 12,
        })
      );
      // หันลูกโลกมาที่ไทย
      chart.set("rotationX", -HUB_LON);
      chart.set("rotationY", -HUB_LAT - 6);

      // ── ทะเล (sphere) ──
      const bg = chart.series.push(am5map.MapPolygonSeries.new(root, {}));
      bg.mapPolygons.template.setAll({
        fill: am5.color(0x0a1836),
        stroke: am5.color(0x22304f),
        strokeWidth: 1,
      });
      bg.data.push({ geometry: am5map.getGeoRectangle(90, 180, -90, -180) });

      // ── เส้นกริดโลก (graticule) ──
      const grat = chart.series.push(am5map.GraticuleSeries.new(root, { step: 15 }));
      grat.mapLines.template.setAll({
        stroke: am5.color(0x22304f),
        strokeOpacity: 0.4,
      });

      // ── แผ่นดิน (ประเทศจริงจาก worldLow) ──
      const polygons = chart.series.push(
        am5map.MapPolygonSeries.new(root, { geoJSON: worldLow, exclude: ["AQ"] })
      );
      polygons.mapPolygons.template.setAll({
        fill: am5.color(0x1c2f5c),
        stroke: am5.color(0x31456f),
        strokeWidth: 0.4,
        tooltipText: "{name}",
        interactive: true,
      });
      polygons.mapPolygons.template.states.create("hover", {
        fill: am5.color(0x27407a),
      });
      // ไฮไลต์ประเทศไทย (ที่ตั้งระบบกลาง)
      polygons.events.on("datavalidated", () => {
        const th = polygons.getDataItemById("TH");
        th?.get("mapPolygon")?.setAll({
          fill: am5.color(0x2a5a8f),
          stroke: am5.color(0x22d3ee),
          strokeWidth: 1,
        });
      });

      // ── series เส้น: น้ำเงิน (ระบบย่อย) + 3 สีความเสี่ยง ──
      function lineSeries(hex: number, width: number, opacity: number) {
        const s = chart.series.push(am5map.MapLineSeries.new(root, {}));
        s.mapLines.template.setAll({
          stroke: am5.color(hex),
          strokeWidth: width,
          strokeOpacity: opacity,
        });
        return s;
      }
      const blueLines = lineSeries(BLUE, 1.6, 0.8);
      const riskLines: Record<string, ReturnType<typeof lineSeries>> = {
        green: lineSeries(RISK_HEX.green, 1.4, 0.65),
        yellow: lineSeries(RISK_HEX.yellow, 1.6, 0.75),
        red: lineSeries(RISK_HEX.red, 1.8, 0.85),
      };

      // ── จุด/ป้าย ── (point series + bullet ตาม dataContext)
      const points = chart.series.push(am5map.MapPointSeries.new(root, {}));
      points.bullets.push((r, _s, dataItem) => {
        const ctx = dataItem.dataContext as {
          radius?: number;
          hex?: number;
          label?: string;
          dy?: number;
          hub?: boolean;
        };
        const container = am5.Container.new(r, {});
        if (ctx.hub) {
          // Hub: วงแหวน + จุด cyan
          container.children.push(
            am5.Circle.new(r, {
              radius: 9,
              fill: am5.color(0x0e2a3a),
              stroke: am5.color(0x22d3ee),
              strokeWidth: 2,
            })
          );
          container.children.push(
            am5.Circle.new(r, { radius: 3, fill: am5.color(0x67e8f9) })
          );
        } else {
          container.children.push(
            am5.Circle.new(r, {
              radius: ctx.radius ?? 3,
              fill: am5.color(ctx.hex ?? 0x7dd3fc),
              stroke: am5.color(0x0b1530),
              strokeWidth: 1,
            })
          );
        }
        if (ctx.label) {
          container.children.push(
            am5.Label.new(r, {
              text: ctx.label,
              fontSize: 10,
              fill: am5.color(0xcbd5e1),
              centerX: am5.p50,
              centerY: 0,
              dy: ctx.dy ?? 10,
              textAlign: "center",
            })
          );
        }
        return am5.Bullet.new(r, { sprite: container });
      });

      // ── จุดวิ่งตามเส้น (แบบ Sankey-map demo) — series แยกต่อสี ──
      function moverSeries(hex: number) {
        const s = chart.series.push(am5map.MapPointSeries.new(root, {}));
        s.bullets.push((r) =>
          am5.Bullet.new(r, {
            sprite: am5.Circle.new(r, { radius: 2.6, fill: am5.color(hex) }),
          })
        );
        return s;
      }
      const moverFor: Record<string, ReturnType<typeof moverSeries>> = {
        blue: moverSeries(BLUE),
        green: moverSeries(RISK_HEX.green),
        yellow: moverSeries(RISK_HEX.yellow),
        red: moverSeries(RISK_HEX.red),
      };
      function addMover(
        color: keyof typeof moverFor,
        lineDI: Parameters<
          typeof moverFor.blue.pushDataItem
        >[0]["lineDataItem"],
        duration: number
      ) {
        const di = moverFor[color].pushDataItem({
          lineDataItem: lineDI,
          positionOnLine: 0,
        });
        di.animate({
          key: "positionOnLine",
          from: 0,
          to: 1,
          duration,
          loops: Infinity,
          easing: am5.ease.linear,
        });
      }

      // ═══ ใส่ข้อมูลจริง ═══
      const hubCoord: [number, number] = [HUB_LON, HUB_LAT];

      // 1) Hub
      const localParts = geoData
        .filter((g) => g.country === "LOCAL")
        .map((g) => {
          const h = RISK_HEX[g.risk].toString(16).padStart(6, "0");
          return `[#${h}]●${g.count}[/]`;
        })
        .join(" ");
      points.data.push({
        geometry: { type: "Point", coordinates: hubCoord },
        hub: true,
        label:
          "ระบบกลาง (HUB)\nม.นราธิวาสราชนครินทร์ · จ.นราธิวาส" +
          (localParts ? `\nภายในวิทยาเขต: ${localParts}` : ""),
        dy: 12,
      });

      // 2) ระบบย่อย — วางรอบวิทยาเขต + เส้นน้ำเงินเข้า Hub
      const activeSubs = subsData.filter((s) => s.status === "active").slice(0, 6);
      activeSubs.forEach((s, i) => {
        const ang = (-30 + i * 42) * (Math.PI / 180);
        const lon = HUB_LON + Math.cos(ang) * 3.2;
        const lat = HUB_LAT + Math.sin(ang) * 3.2;
        const hex = HEALTH_HEX[s.health || ""] ?? 0x64748b;
        const li = blueLines.pushDataItem({
          geometry: {
            type: "LineString",
            coordinates: [hubCoord, [lon, lat]],
          },
        });
        addMover("blue", li, 2200 + i * 300);
        points.data.push({
          geometry: { type: "Point", coordinates: [lon, lat] },
          radius: 3.5,
          hex,
          label: s.name.length > 12 ? s.name.slice(0, 11) + "…" : s.name,
          dy: 6,
        });
      });

      // 3) ผู้ใช้ต่างพิกัด → Hub (เส้นสีตามความเสี่ยง + จุดวิ่ง)
      const totals = new Map<string, number>();
      for (const g of geoData)
        if (g.country !== "LOCAL")
          totals.set(g.country, (totals.get(g.country) || 0) + g.count);

      geoData
        .filter((g) => g.country !== "LOCAL" && CENTROID[g.country])
        .forEach((g, i) => {
          const [lat, lon] = CENTROID[g.country];
          const li = riskLines[g.risk].pushDataItem({
            geometry: {
              type: "LineString",
              coordinates: [[lon, lat], hubCoord],
            },
          });
          addMover(g.risk, li, 2800 + i * 350);
        });
      // marker ประเทศ (รวมทุก bucket)
      for (const [c, n] of totals) {
        const cen = CENTROID[c];
        if (!cen) continue;
        points.data.push({
          geometry: { type: "Point", coordinates: [cen[1], cen[0]] },
          radius: 3 + Math.min(5, Math.sqrt(n)),
          hex: 0x7dd3fc,
          label: `${c} · ${n}`,
          dy: -22,
        });
      }

      chart.appear(600, 80);
    })();

    return () => {
      disposed = true;
      rootObj?.dispose();
    };
    // สร้างครั้งเดียว — data refresh ใช้ค่าแรก (map เป็นภาพรวม 30 วัน เปลี่ยนช้า)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <div ref={chartRef} className="w-full h-[430px]" />
      <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 pb-2 text-[10px] font-mono text-slate-400">
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-4 h-0.5 bg-emerald-400" /> ปลอดภัย (&lt;0.40)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-4 h-0.5 bg-amber-400" /> เฝ้าระวัง (0.40–0.49)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-4 h-0.5 bg-rose-400" /> เสี่ยงสูง (≥0.50)
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-4 h-0.5 bg-blue-500" /> เชื่อมระบบย่อย
        </span>
        <span className="text-slate-500">· ลากเพื่อหมุนโลก</span>
      </div>
    </div>
  );
}
