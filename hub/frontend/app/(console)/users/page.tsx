"use client";

import { useEffect, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge } from "@/components/Badge";
import { clientFetch } from "@/lib/api";

type User = {
  id: string;
  email: string;
  full_name: string;
  user_type: string;
  identifier?: string;
  faculty?: string;
  major?: string;
  year_or_position?: string;
  status: string;
  [k: string]: unknown;
};

const TYPE_TONE: Record<string, "brand" | "good" | "warn" | "danger" | "default"> = {
  student: "brand",
  teacher: "good",
  staff: "warn",
  admin: "danger",
};

export default function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [type, setType] = useState<string>("");
  const [faculty, setFaculty] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setLoading(true);
    setError(null);
    const qs = new URLSearchParams();
    if (type) qs.set("user_type", type);
    if (faculty) qs.set("faculty", faculty);
    qs.set("limit", "200");
    clientFetch<User[]>(`/admin/users/?${qs.toString()}`)
      .then(setUsers)
      .catch((e) => setError(e.detail || "โหลดข้อมูลไม่สำเร็จ"))
      .finally(() => setLoading(false));
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [type, faculty]);

  const columns: Column<User>[] = [
    {
      key: "full_name",
      header: "ชื่อ",
      render: (u) => (
        <div>
          <div className="font-semibold text-ink-900">{u.full_name}</div>
          <div className="text-xs text-ink-500 font-mono">{u.email}</div>
        </div>
      ),
    },
    {
      key: "user_type",
      header: "ประเภท",
      render: (u) => (
        <Badge tone={TYPE_TONE[u.user_type] || "default"}>{u.user_type}</Badge>
      ),
    },
    {
      key: "identifier",
      header: "รหัส",
      render: (u) => (
        <span className="font-mono text-xs">{u.identifier || "—"}</span>
      ),
    },
    {
      key: "faculty",
      header: "คณะ",
      render: (u) => u.faculty || "—",
    },
    {
      key: "major",
      header: "สาขา / ตำแหน่ง",
      render: (u) => (
        <span className="text-xs">
          {u.major || u.year_or_position || "—"}
        </span>
      ),
    },
    {
      key: "status",
      header: "สถานะ",
      render: (u) => (
        <Badge tone={u.status === "active" ? "good" : "danger"}>
          {u.status}
        </Badge>
      ),
    },
  ];

  return (
    <>
      <Topbar title="ผู้ใช้งาน" />
      <main className="p-8 max-w-7xl mx-auto w-full">
        <div className="mb-5 flex flex-wrap items-center gap-3">
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="px-3 py-2 rounded-lg border border-ink-200 bg-white text-sm focus:outline-none focus:border-brand-500"
          >
            <option value="">ทุกประเภท</option>
            <option value="student">นักศึกษา</option>
            <option value="teacher">อาจารย์</option>
            <option value="staff">เจ้าหน้าที่</option>
            <option value="admin">Admin</option>
          </select>
          <input
            type="text"
            placeholder="กรองตามคณะ…"
            value={faculty}
            onChange={(e) => setFaculty(e.target.value)}
            className="px-3 py-2 rounded-lg border border-ink-200 bg-white text-sm focus:outline-none focus:border-brand-500 w-56"
          />
          <div className="ml-auto text-xs text-ink-500">
            {loading ? "กำลังโหลด…" : `${users.length} รายการ`}
          </div>
        </div>

        {error && (
          <div className="mb-5 p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm">
            {error}
          </div>
        )}

        <DataTable columns={columns} rows={users} emptyMessage="ไม่พบผู้ใช้" />
      </main>
    </>
  );
}
