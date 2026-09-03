"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Topbar } from "@/components/Topbar";
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
  [key: string]: unknown;
};

export default function UsersPage() {
  const router = useRouter();
  const [users, setUsers] = useState<User[]>([]);
  const [type, setType] = useState("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [formModal, setFormModal] = useState<{ mode: "create" | "edit"; user?: UserRow } | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  function load() {
    setLoading(true);
    setError(null);
    const query = new URLSearchParams({ limit: "200" });
    if (type) query.set("user_type", type);
    if (debouncedSearch.trim()) query.set("q", debouncedSearch.trim());
    clientFetch<User[]>(`/admin/users/?${query.toString()}`)
      .then(setUsers)
      .catch((cause) => setError(cause.detail || "โหลดข้อมูลไม่สำเร็จ"))
      .finally(() => setLoading(false));
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [type, debouncedSearch]);

  const students = users.filter((user) => user.user_type === "student").length;
  const staff = users.filter((user) => ["teacher", "staff"].includes(user.user_type)).length;
  const admins = users.filter((user) => user.user_type === "admin").length;
  const actions = <button className="cx-primary-action" type="button" onClick={() => setFormModal({ mode: "create" })}>+ เพิ่มผู้ใช้งาน</button>;

  return (
    <>
      <Topbar title="ผู้ใช้งาน" actions={actions} />
      <main className="cx-document">
        <section className="cx-kpis four" aria-label="สรุปผู้ใช้งาน">
          <article className="cx-kpi signal"><span className="mono">TOTAL USERS</span><strong>{users.length}</strong><small className="mono">ALL IDENTITIES</small></article>
          <article className="cx-kpi"><span className="mono">STUDENTS</span><strong>{students}</strong><small className="mono">STUDENT ACCOUNTS</small></article>
          <article className="cx-kpi"><span className="mono">TEACHER / STAFF</span><strong>{staff}</strong><small className="mono">PERSONNEL</small></article>
          <article className="cx-kpi danger"><span className="mono">ADMIN</span><strong>{admins}</strong><small className="mono">PRIVILEGED ACCESS</small></article>
        </section>

        {error && <div className="cx-alert danger" role="alert">{error}</div>}

        <section className="cx-panel">
          <header>
            <div><span className="mono">IDENTITY DIRECTORY</span><h2>รายชื่อผู้ใช้งาน</h2></div>
            <span className="cx-data">{loading ? "LOADING" : `${users.length} RECORDS`}</span>
          </header>
          <div className="cx-toolbar">
            <label><SearchIcon /><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="ชื่อ, อีเมล, รหัส, คณะ หรือสาขา..." /></label>
            <select value={type} onChange={(event) => setType(event.target.value)}>
              <option value="">ทุกประเภท</option><option value="student">นักศึกษา</option><option value="teacher">อาจารย์</option><option value="staff">เจ้าหน้าที่</option><option value="admin">Admin</option>
            </select>
            {search && <button type="button" onClick={() => setSearch("")}>ล้างคำค้น</button>}
          </div>
          <div className="cx-table-wrap">
            <table>
              <thead><tr><th>IDENTITY</th><th>ROLE</th><th>IDENTIFIER</th><th>FACULTY / POSITION</th><th>STATUS</th><th aria-label="actions" /></tr></thead>
              <tbody>
                {!loading && users.length === 0 && <tr><td colSpan={6}><div className="cx-empty"><strong>ไม่พบผู้ใช้งาน</strong><span className="mono">NO MATCHING IDENTITIES</span></div></td></tr>}
                {users.map((user) => (
                  <tr key={user.id} onClick={() => router.push(`/users/${user.id}`)} className="cx-clickable-row">
                    <td><b>{user.full_name || "ไม่ระบุชื่อ"}</b><small className="cx-data">{user.email}</small></td>
                    <td><span className={`cx-chip ${user.user_type === "admin" ? "danger" : user.user_type === "staff" ? "warn" : "outline"}`}>{user.user_type}</span></td>
                    <td><code>{user.identifier || "—"}</code></td>
                    <td><span>{user.faculty || "—"}</span><small className="cx-data">{user.major || user.year_or_position || ""}</small></td>
                    <td><span className={`cx-chip ${user.status === "active" ? "signal" : user.status === "suspended" ? "warn" : "danger"}`}>{user.status}</span></td>
                    <td>→</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </main>

      {formModal && <UserFormModal mode={formModal.mode} user={formModal.user} onClose={() => setFormModal(null)} onSaved={() => { setFormModal(null); load(); }} />}
    </>
  );
}

function SearchIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>;
}
