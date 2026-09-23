"use client";

/**
 * รายงานสรุปประจำเดือนสำหรับผู้บริหาร — เลือกเดือนตามปฏิทินเวลาไทย + เทียบเดือนก่อน
 * ข้อมูลจาก GET /admin/reports/monthly?month=YYYY-MM (ทุกค่ามาจาก DB จริง)
 * เนื้อหาเอกสารอยู่ใน _components/ReportDocument.tsx
 * พิมพ์ / บันทึกเป็น PDF ผ่านเบราว์เซอร์ — print CSS ซ่อนเมนูและปุ่มควบคุม
 */

import { useEffect, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";
import { ReportDocument } from "./_components/ReportDocument";
import type { Report } from "./_types";
import "../../../signal-room.css";
import "../../../signal-console.css";

/** เดือนที่แล้วตามเวลาไทย — ผู้บริหารมักดูเดือนที่ปิดยอดแล้ว */
function defaultMonth(): string {
  const bkk = new Date(Date.now() + 7 * 3600_000);
  let y = bkk.getUTCFullYear();
  let m = bkk.getUTCMonth(); // 0-based → เท่ากับเลขเดือนก่อนหน้าพอดี
  if (m === 0) {
    y -= 1;
    m = 12;
  }
  return `${y}-${String(m).padStart(2, "0")}`;
}

export default function MonthlyReportPage() {
  const [month, setMonth] = useState(defaultMonth);
  const [data, setData] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setData(null);
    setError(null);
    clientFetch<Report>(`/admin/reports/monthly?month=${month}`)
      .then((r) => {
        if (alive) setData(r);
      })
      .catch((e) => {
        if (alive) setError(e.detail || "โหลดรายงานไม่สำเร็จ");
      });
    return () => {
      alive = false;
    };
  }, [month]);

  return (
    <div className="sc">
      <Topbar title="Monthly Report" />

      <section className="cx-command no-print">
        <div>
          <span>
            <span className="cx-dot">
              <i />
            </span>
            executive report
          </span>
          <h1>Monthly Report</h1>
        </div>
        <div className="cx-report-controls">
          <small>ข้อความในรายงานแก้ไขได้ก่อนพิมพ์</small>
          <input
            type="month"
            value={month}
            max={defaultMonth()}
            onChange={(e) => {
              if (e.target.value) setMonth(e.target.value);
            }}
            aria-label="เลือกเดือน"
          />
          <button
            type="button"
            className="cx-add-button"
            onClick={() => window.print()}
            disabled={!data}
          >
            พิมพ์ / บันทึก PDF
          </button>
        </div>
      </section>

      <ReportDocument month={month} data={data} error={error} />
    </div>
  );
}
