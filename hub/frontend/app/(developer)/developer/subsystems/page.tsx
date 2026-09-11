"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge } from "@/components/Badge";
import { clientFetch } from "@/lib/api";
// design system เดียวกับหน้าคอนโซล — .sc = ชุด cx-*
import "../../../signal-room.css";
import "../../../signal-console.css";

type Subsystem = {
  id: string;
  name: string;
  description?: string | null;
  client_id: string;
  status: string;
  scope: string[];
  created_at: string;
  [k: string]: unknown;
};

const STATUS_TONE: Record<string, "good" | "warn" | "danger" | "default"> = {
  active: "good",
  pending: "warn",
  suspended: "danger",
};

const STATUS_LABEL: Record<string, string> = {
  active: "พร้อมใช้งาน",
  pending: "รออนุมัติ",
  suspended: "ถูกระงับ",
};

export default function MySubsystemsPage() {
  const [subs, setSubs] = useState<Subsystem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    clientFetch<Subsystem[]>("/developer/subsystems")
      .then(setSubs)
      .catch((e) => setError(e.detail || "โหลดข้อมูลไม่สำเร็จ"));
  }, []);

  const rows = subs ?? [];

  // B51: subs === null คือ "ยังไม่โหลด" → KPI แสดง "—" ไม่ใช่ 0
  const counts = useMemo(
    () => ({
      total: rows.length,
      active: rows.filter((s) => s.status === "active").length,
      pending: rows.filter((s) => s.status === "pending").length,
      suspended: rows.filter((s) => s.status === "suspended").length,
    }),
    [rows]
  );

  const columns: Column<Subsystem>[] = [
    {
      key: "name",
      header: "ชื่อระบบ",
      render: (s) => (
        <Link href={`/developer/subsystems/${s.id}`} className="cx-row-link">
          <div>{s.name}</div>
          <div className="cx-data">{s.client_id}</div>
          {s.description && <div className="cx-sub">{s.description}</div>}
        </Link>
      ),
    },
    {
      key: "status",
      header: "สถานะ",
      width: "130px",
      render: (s) => (
        <Badge tone={STATUS_TONE[s.status] || "default"}>
          {STATUS_LABEL[s.status] || s.status}
        </Badge>
      ),
    },
    {
      key: "scope",
      header: "Scope ที่ขอ",
      render: (s) => (
        <div className="flex flex-wrap gap-1">
          {s.scope.slice(0, 4).map((sc) => (
            <span key={sc} className="cx-tag all">
              {sc}
            </span>
          ))}
          {s.scope.length > 4 && (
            <span className="cx-sub">+{s.scope.length - 4}</span>
          )}
        </div>
      ),
    },
    {
      key: "created_at",
      header: "ลงทะเบียนเมื่อ",
      width: "130px",
      render: (s) => (
        <span className="cx-data">
          {new Date(s.created_at).toISOString().slice(0, 10)}
        </span>
      ),
    },
  ];

  return (
    <div className="sc">
      <Topbar title="My Subsystems" />

      <section className="cx-command">
        <div>
          <span>
            <span className="cx-dot">
              <i />
            </span>
            developer portal
          </span>
          <h1>My Subsystems</h1>
        </div>
        <Link href="/developer/subsystems/new" className="cx-add-button">
          + ลงทะเบียนระบบใหม่
        </Link>
      </section>

      <main className="cx-document">
        <section className="cx-kpis four">
          {[
            { k: "total", label: "total", v: counts.total, sub: "ระบบที่คุณลงทะเบียน" },
            { k: "active", label: "active", v: counts.active, sub: "พร้อมใช้งาน", tone: "signal" },
            { k: "pending", label: "pending", v: counts.pending, sub: "รอผู้ดูแลอนุมัติ", tone: "warn" },
            { k: "suspended", label: "suspended", v: counts.suspended, sub: "ถูกระงับ", tone: "danger" },
          ].map((c) => (
            <article key={c.k} className={`cx-kpi${c.tone ? " " + c.tone : ""}`}>
              <span>{c.label}</span>
              <strong className="mono">{subs === null ? "—" : c.v}</strong>
              <small className="mono">
                {subs === null ? "waiting for api" : c.sub}
              </small>
            </article>
          ))}
        </section>

        {error && <div className="cx-msg err">{error}</div>}

        <section className="cx-panel">
          <header>
            <div>
              <span>registered clients</span>
              <h2>ระบบที่คุณลงทะเบียน</h2>
            </div>
            <span className="cx-chip mono">
              {subs === null ? "กำลังโหลด…" : `${rows.length} รายการ`}
            </span>
          </header>

          {subs !== null && rows.length === 0 ? (
            <div className="cx-empty">
              <strong>ยังไม่ได้ลงทะเบียนระบบย่อย</strong>
              <span>
                เริ่มต้นโดยกรอกรายละเอียดของระบบที่ต้องการเชื่อมกับ Hub — เช่น
                ระบบจองห้อง ระบบทะเบียน หรือระบบใด ๆ ที่ต้อง authenticate user
              </span>
              <Link href="/developer/subsystems/new" className="cx-add-button">
                เริ่มลงทะเบียน
              </Link>
            </div>
          ) : (
            <div className="cx-table-wrap">
              <DataTable
                columns={columns}
                rows={rows}
                emptyMessage={subs === null ? "กำลังโหลด…" : "ยังไม่มีระบบ"}
              />
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
