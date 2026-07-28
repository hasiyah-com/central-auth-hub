"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Topbar } from "@/components/Topbar";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge } from "@/components/Badge";
import { clientFetch } from "@/lib/api";
import { UserFormModal, type UserRow } from "./_components/UserFormModal";

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

const STATUS_TONE: Record<string, "brand" | "good" | "warn" | "danger" | "default"> = {
  active: "good",
  suspended: "warn",
  graduated: "brand",
  resigned: "default",
  deleted: "danger",
};

export default function UsersPage() {
  const router = useRouter();
  const [users, setUsers] = useState<User[]>([]);
  const [type, setType] = useState<string>("");
  const [search, setSearch] = useState<string>("");
  // ค่าที่ยิงจริงหลัง debounce — กันยิง request ทุกตัวอักษรที่พิมพ์
  const [debouncedSearch, setDebouncedSearch] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [formModal, setFormModal] = useState<{ mode: "create" | "edit"; user?: UserRow } | null>(null);

  // debounce 300ms — พิมพ์ต่อเนื่องยิงครั้งเดียวตอนหยุดพิมพ์
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  function load() {
    setLoading(true);
    setError(null);
    const qs = new URLSearchParams();
    if (type) qs.set("user_type", type);
    if (debouncedSearch.trim()) qs.set("q", debouncedSearch.trim());
    qs.set("limit", "200");
    clientFetch<User[]>(`/admin/users/?${qs.toString()}`)
      .then(setUsers)
      .catch((e) => setError(e.detail || "โหลดข้อมูลไม่สำเร็จ"))
      .finally(() => setLoading(false));
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [type, debouncedSearch]);

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
        <Badge tone={STATUS_TONE[u.status] || "danger"}>{u.status}</Badge>
      ),
    },
    {
      key: "_go",
      header: "",
      align: "right",
      render: () => <span className="text-ink-300 text-sm">›</span>,
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
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400 text-sm pointer-events-none">
              🔍
            </span>
            <input
              type="text"
              placeholder="ค้นหา ชื่อ, อีเมล, รหัส, คณะ, สาขา…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 pr-8 py-2 rounded-lg border border-ink-200 bg-white text-sm focus:outline-none focus:border-brand-500 w-72"
            />
            {search && (
              <button
                onClick={() => setSearch("")}
                title="ล้างคำค้นหา"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-400 hover:text-ink-700 text-sm"
              >
                ✕
              </button>
            )}
          </div>
          <button
            onClick={() => setFormModal({ mode: "create" })}
            className="ml-auto px-4 py-2 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-700"
          >
            + เพิ่มผู้ใช้
          </button>
          <div className="text-xs text-ink-500">
            {loading
              ? "กำลังโหลด…"
              : debouncedSearch.trim()
                ? `พบ ${users.length} รายการ จากคำค้น "${debouncedSearch.trim()}"`
                : `${users.length} รายการ`}
          </div>
        </div>

        {error && (
          <div className="mb-5 p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm">
            {error}
          </div>
        )}

        <DataTable
          columns={columns}
          rows={users}
          emptyMessage={
            debouncedSearch.trim()
              ? `ไม่พบผู้ใช้ที่ตรงกับ "${debouncedSearch.trim()}"`
              : "ไม่พบผู้ใช้"
          }
          onRowClick={(u) => router.push(`/users/${u.id}`)}
        />
      </main>

      {formModal && (
        <UserFormModal
          mode={formModal.mode}
          user={formModal.user}
          onClose={() => setFormModal(null)}
          onSaved={() => {
            setFormModal(null);
            load();
          }}
        />
      )}
    </>
  );
}
