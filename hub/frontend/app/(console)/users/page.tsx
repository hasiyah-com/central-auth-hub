"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Topbar } from "@/components/Topbar";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge } from "@/components/Badge";
import { clientFetch } from "@/lib/api";
// design system ที่ port จากดีไซน์ตัวจริง — .sc = ชุด cx-* ของหน้าคอนโซล
import "../../signal-room.css";
import "../../signal-console.css";
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
  // จำนวนผู้ใช้แยกตามประเภท — ใช้กับ KPI 4 ใบด้านบน (ข้อมูลจริง ไม่ใช่ค่าสมมติ)
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  useEffect(() => {
    clientFetch<Record<string, number>>("/admin/users/count")
      .then(setCounts)
      .catch(() => {});
  }, []);

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

  const teacherStaff =
    counts === null ? null : (counts.teacher ?? 0) + (counts.staff ?? 0);
  // /admin/users/count คืนเฉพาะจำนวนแยกตาม user_type (ไม่มีคีย์ total) — รวมเองที่ฝั่ง frontend
  const totalUsers =
    counts === null ? null : Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <div className="sc">
      <Topbar title="ผู้ใช้งาน" />

      <section className="cx-command">
        <div>
          <span>
            <span className="cx-dot">
              <i />
            </span>
            control surface
          </span>
          <h1>Users</h1>
        </div>
        <button
          onClick={() => setFormModal({ mode: "create" })}
          className="cx-add-button"
        >
          + เพิ่มผู้ใช้งาน
        </button>
      </section>

      <main className="cx-document">
        {/* KPI — ข้อมูลจริงจาก /admin/users/count (B51: แยก "ยังไม่โหลด" ออกจาก 0 จริง) */}
        <section className="cx-kpis four">
          {[
            { k: "total", label: "total users", v: totalUsers ?? undefined, tone: "signal" },
            { k: "student", label: "student", v: counts?.student },
            { k: "staff", label: "teacher / staff", v: teacherStaff ?? undefined },
            { k: "admin", label: "admin", v: counts?.admin },
          ].map((c) => (
            <article key={c.k} className={`cx-kpi${c.tone ? " " + c.tone : ""}`}>
              <span>{c.label}</span>
              <strong className="mono">{counts === null ? "—" : (c.v ?? 0)}</strong>
              <small className="mono">
                {counts === null ? "กำลังโหลด" : "จากฐานข้อมูลผู้ใช้"}
              </small>
            </article>
          ))}
        </section>

        {error && (
          <div className="mb-2.5 border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
            {error}
          </div>
        )}

        <section className="cx-panel">
          <header>
            <div>
              <span>identity directory</span>
              <h2>User Directory</h2>
            </div>
            <span className="cx-chip mono">
              {loading ? "กำลังโหลด…" : `${users.length} รายการ`}
            </span>
          </header>

          <div className="cx-toolbar">
            <label>
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                aria-hidden="true"
              >
                <circle cx="11" cy="11" r="7" />
                <path d="m20 20-3.5-3.5" />
              </svg>
              <input
                type="text"
                placeholder="ค้นหา ชื่อ อีเมล รหัส คณะ สาขา"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>

            <select value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">ทุกประเภท</option>
              <option value="student">นักศึกษา</option>
              <option value="teacher">อาจารย์</option>
              <option value="staff">เจ้าหน้าที่</option>
              <option value="admin">Admin</option>
            </select>

            {(search || type) && (
              <button
                onClick={() => {
                  setSearch("");
                  setType("");
                }}
                className="cx-chip"
              >
                ล้างตัวกรอง
              </button>
            )}
          </div>

          <div className="cx-table-wrap">
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
          </div>
        </section>
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
    </div>
  );
}
