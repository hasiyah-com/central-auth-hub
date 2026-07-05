"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge } from "@/components/Badge";
import { clientFetch } from "@/lib/api";

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
  const [subs, setSubs] = useState<Subsystem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    clientFetch<Subsystem[]>("/developer/subsystems")
      .then((d) => setSubs(d))
      .catch((e) => setError(e.detail || "โหลดข้อมูลไม่สำเร็จ"))
      .finally(() => setLoading(false));
  }, []);

  const columns: Column<Subsystem>[] = [
    {
      key: "name",
      header: "ชื่อระบบ",
      render: (s) => (
        <Link
          href={`/developer/subsystems/${s.id}`}
          className="block hover:bg-ink-50 -mx-2 px-2 py-1 rounded transition group"
        >
          <div className="font-semibold text-ink-900 group-hover:text-brand-700">
            {s.name}{" "}
            <span className="text-ink-400 text-xs"> </span>
          </div>
          <div className="text-xs text-ink-500 font-mono">{s.client_id}</div>
          {s.description && (
            <div className="text-xs text-ink-400 mt-0.5 max-w-md truncate">
              {s.description}
            </div>
          )}
        </Link>
      ),
    },
    {
      key: "status",
      header: "สถานะ",
      width: "140px",
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
            <span
              key={sc}
              className="px-1.5 py-0.5 rounded bg-brand-50 text-brand-700 text-[10px] font-mono font-semibold border border-brand-100"
            >
              {sc}
            </span>
          ))}
          {s.scope.length > 4 && (
            <span className="text-[10px] text-ink-500">
              +{s.scope.length - 4}
            </span>
          )}
        </div>
      ),
    },
    {
      key: "created_at",
      header: "ลงทะเบียนเมื่อ",
      width: "140px",
      render: (s) => (
        <span className="font-mono text-[11px] text-ink-500">
          {new Date(s.created_at).toISOString().slice(0, 10)}
        </span>
      ),
    },
  ];

  return (
    <>
      <Topbar title="ระบบของฉัน" />
      <main className="p-8 max-w-7xl mx-auto w-full">
        <div className="mb-6 flex items-end justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-sm font-bold text-ink-500 uppercase tracking-wider">
              Developer Portal · ระบบที่คุณลงทะเบียน
            </h2>
            <p className="text-xs text-ink-400 mt-1">
              {/* ระบบย่อยที่คุณเป็นเจ้าของ — จัดการ whitelist + ดูสถานะการอนุมัติ */}
            </p>
          </div>
          <Link
            href="/developer/subsystems/new"
            className="px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-700 text-white text-sm font-semibold transition shadow-sm"
          >
            + ลงทะเบียนระบบใหม่
          </Link>
        </div>

        {error && (
          <div className="mb-5 p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm">
            {error}
          </div>
        )}

        {loading ? (
          <div className="text-ink-400 text-sm">กำลังโหลด…</div>
        ) : subs.length === 0 ? (
          <div className="bg-white rounded-xl border border-ink-200 shadow-sm p-12 text-center">
            <div className="text-5xl mb-3">🌱</div>
            <h3 className="text-lg font-bold text-ink-900 mb-2">
              ยังไม่ได้ลงทะเบียนระบบย่อย
            </h3>
            <p className="text-sm text-ink-500 max-w-md mx-auto mb-6">
              เริ่มต้นโดยกรอกรายละเอียดของระบบที่ต้องการเชื่อมกับ Hub —
              เช่น ระบบจองห้อง ระบบทะเบียน หรือระบบใด ๆ ที่ต้อง authenticate user
            </p>
            <Link
              href="/developer/subsystems/new"
              className="inline-block px-5 py-2.5 rounded-lg bg-brand-600 hover:bg-brand-700 text-white text-sm font-semibold transition"
            >
              เริ่มลงทะเบียน →
            </Link>
          </div>
        ) : (
          <DataTable
            columns={columns}
            rows={subs}
            emptyMessage="ยังไม่มีระบบ"
          />
        )}
      </main>
    </>
  );
}
