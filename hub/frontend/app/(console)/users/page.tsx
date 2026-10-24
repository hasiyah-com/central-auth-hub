"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Topbar } from "@/components/Topbar";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge } from "@/components/Badge";
import { clientFetch } from "@/lib/api";
import { mutateWithStepup } from "@/lib/passkey";
// design system ที่ port จากดีไซน์ตัวจริง — .sc = ชุด cx-* ของหน้าคอนโซล
import "../../signal-room.css";
import "../../signal-console.css";
import { UserFormModal, type UserRow } from "./_components/UserFormModal";
import { StatusImportModal } from "./_components/StatusImportModal";

type UserFilterOptions = {
  faculties: string[];
  majors: string[];
  positions: string[];
  statuses: string[];
};

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

type RegistrationDomainsResponse = {
  domains: string[];
  usage?: Record<string, Array<{ id: string; name: string }>>;
  affected_subsystems?: Array<{
    id: string;
    name: string;
    disabled_domains: string[];
  }>;
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
  const [faculty, setFaculty] = useState("");
  const [major, setMajor] = useState("");
  const [position, setPosition] = useState("");
  const [status, setStatus] = useState("");
  const [filterOptions, setFilterOptions] = useState<UserFilterOptions>({
    faculties: [], majors: [], positions: [], statuses: [],
  });
  const [search, setSearch] = useState<string>("");
  // ค่าที่ยิงจริงหลัง debounce — กันยิง request ทุกตัวอักษรที่พิมพ์
  const [debouncedSearch, setDebouncedSearch] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [formModal, setFormModal] = useState<{ mode: "create" | "edit"; user?: UserRow } | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  // จำนวนผู้ใช้แยกตามประเภท — ใช้กับ KPI 4 ใบด้านบน (ข้อมูลจริง ไม่ใช่ค่าสมมติ)
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  const [registrationDomains, setRegistrationDomains] = useState<string[]>([]);
  const [domainUsage, setDomainUsage] = useState<RegistrationDomainsResponse["usage"]>({});
  const [newDomain, setNewDomain] = useState("");
  const [domainBusy, setDomainBusy] = useState(false);
  const [domainError, setDomainError] = useState<string | null>(null);
  const [domainNotice, setDomainNotice] = useState<string | null>(null);
  useEffect(() => {
    clientFetch<Record<string, number>>("/admin/users/count")
      .then(setCounts)
      .catch(() => {});
  }, []);

  function loadRegistrationDomains() {
    clientFetch<RegistrationDomainsResponse>("/admin/users/registration-domains")
      .then((data) => {
        setRegistrationDomains(data.domains);
        setDomainUsage(data.usage || {});
      })
      .catch((e) => setDomainError(e.detail || "โหลด Domain กลางไม่สำเร็จ"));
  }

  useEffect(loadRegistrationDomains, []);

  async function saveRegistrationDomains(domains: string[]) {
    setDomainBusy(true);
    setDomainError(null);
    setDomainNotice(null);
    try {
      const result = await mutateWithStepup<RegistrationDomainsResponse>(
        "/admin/users/registration-domains",
        { method: "PUT", body: JSON.stringify({ domains }) }
      );
      setRegistrationDomains(result.domains);
      setNewDomain("");
      const affected = result.affected_subsystems || [];
      if (affected.length) {
        setDomainNotice(
          `ปิดสิทธิ์สมัครของ ${affected.length} ระบบย่อยสำหรับ Domain ที่ถูกนำออกแล้ว`
        );
      }
      loadRegistrationDomains();
    } catch (e) {
      const detail = (e as { detail?: string | { message?: string } })?.detail;
      setDomainError(
        typeof detail === "string" ? detail : detail?.message || "บันทึก Domain ไม่สำเร็จ"
      );
    } finally {
      setDomainBusy(false);
    }
  }

  function addRegistrationDomain() {
    const domain = newDomain.trim().toLowerCase().replace(/^@+/, "");
    if (!domain) return;
    if (registrationDomains.includes(domain)) {
      setDomainError("Domain นี้มีอยู่แล้ว");
      return;
    }
    void saveRegistrationDomains([...registrationDomains, domain]);
  }

  function removeRegistrationDomain(domain: string) {
    const usedBy = domainUsage?.[domain] || [];
    const warning = usedBy.length
      ? `Domain นี้ถูกใช้โดย ${usedBy.length} ระบบย่อย การลบจะหยุดรับผู้ใช้ใหม่จาก Domain นี้ ยืนยันหรือไม่?`
      : `ลบ ${domain} ออกจาก Domain กลางหรือไม่?`;
    if (!window.confirm(warning)) return;
    void saveRegistrationDomains(registrationDomains.filter((d) => d !== domain));
  }

  useEffect(() => {
    clientFetch<UserFilterOptions>("/admin/users/filter-options")
      .then(setFilterOptions)
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
    if (faculty) qs.set("faculty", faculty);
    if (major) qs.set("major", major);
    if (position) qs.set("position", position);
    if (status) qs.set("status", status);
    if (debouncedSearch.trim()) qs.set("q", debouncedSearch.trim());
    qs.set("limit", "200");
    clientFetch<User[]>(`/admin/users/?${qs.toString()}`)
      .then(setUsers)
      .catch((e) => setError(e.detail || "โหลดข้อมูลไม่สำเร็จ"))
      .finally(() => setLoading(false));
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [type, faculty, major, position, status, debouncedSearch]);

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
      <Topbar title="Users" />

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
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => setImportOpen(true)}
            className="cx-add-button w-[162px] justify-center !border-slate-300 !bg-white !text-slate-800 hover:!bg-slate-50">
            Import / Export
          </button>
          <button
            onClick={() => setFormModal({ mode: "create" })}
            className="cx-add-button w-[162px] justify-center"
          >
            + เพิ่มผู้ใช้งาน
          </button>
        </div>
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

        <section className="cx-panel">
          <header>
            <div>
              <span>registration trust policy</span>
              <h2>Trusted Registration Domains</h2>
            </div>
            <span className="cx-chip mono">{registrationDomains.length} domains</span>
          </header>
          <div className="cx-panel-body space-y-4">
            <p className="text-sm text-ink-600">
              Domain กลางคือรายการที่องค์กรรับรอง ระบบย่อยเลือกใช้ได้เฉพาะ Domain ในรายการนี้ และผู้ใช้ใหม่ต้องผ่านทั้งสองชั้น
            </p>
            <div className="flex flex-wrap gap-2">
              <input
                aria-label="Domain ใหม่"
                value={newDomain}
                onChange={(e) => setNewDomain(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addRegistrationDomain();
                  }
                }}
                placeholder="uni.ac.th (ไม่ต้องใส่ @)"
                className="h-10 min-w-[260px] flex-1 px-3 rounded-lg border border-ink-200 focus:outline-none focus:border-brand-500 text-sm font-mono"
              />
              <button
                type="button"
                onClick={addRegistrationDomain}
                disabled={domainBusy || !newDomain.trim()}
                className="cx-add-button disabled:opacity-50"
              >
                {domainBusy ? "กำลังบันทึก…" : "+ เพิ่ม Domain"}
              </button>
            </div>
            {domainError && (
              <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{domainError}</div>
            )}
            {domainNotice && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">{domainNotice}</div>
            )}
            {registrationDomains.length ? (
              <div className="grid gap-2 md:grid-cols-2">
                {registrationDomains.map((domain) => {
                  const systems = domainUsage?.[domain] || [];
                  return (
                    <div key={domain} className="flex items-center justify-between gap-3 rounded-lg border border-ink-200 bg-white p-3">
                      <div className="min-w-0">
                        <div className="font-mono text-sm font-semibold text-ink-900">{domain}</div>
                        <div className="truncate text-xs text-ink-500">
                          {systems.length ? `ใช้งานใน ${systems.map((s) => s.name).join(", ")}` : "ยังไม่มีระบบย่อยเลือกใช้"}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => removeRegistrationDomain(domain)}
                        disabled={domainBusy}
                        className="shrink-0 rounded-md border border-rose-200 px-2.5 py-1 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50"
                      >
                        ลบ
                      </button>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-sm text-ink-400">ยังไม่มี Domain กลาง — ระบบย่อยจะยังเปิดรับผู้ใช้ใหม่ไม่ได้</p>
            )}
          </div>
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

            <select
              aria-label="กรองตามประเภทผู้ใช้"
              value={type}
              onChange={(e) => setType(e.target.value)}
            >
              <option value="">ทุกประเภท</option>
              <option value="student">นักศึกษา</option>
              <option value="teacher">อาจารย์</option>
              <option value="staff">เจ้าหน้าที่</option>
              <option value="admin">Admin</option>
            </select>

            <select
              aria-label="กรองตามคณะ"
              value={faculty}
              onChange={(e) => setFaculty(e.target.value)}
            >
              <option value="">ทุกคณะ</option>
              {filterOptions.faculties.map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>

            <select
              aria-label="กรองตามสาขา"
              value={major}
              onChange={(e) => setMajor(e.target.value)}
            >
              <option value="">ทุกสาขา</option>
              {filterOptions.majors.map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>

            <select
              aria-label="กรองตามตำแหน่ง"
              value={position}
              onChange={(e) => setPosition(e.target.value)}
            >
              <option value="">ทุกตำแหน่ง</option>
              {filterOptions.positions.map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>

            <select
              aria-label="กรองตามสถานะผู้ใช้"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="">ทุกสถานะ</option>
              {filterOptions.statuses.map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>

            {(search || type || faculty || major || position || status) && (
              <button
                type="button"
                onClick={() => {
                  setSearch("");
                  setType("");
                  setFaculty("");
                  setMajor("");
                  setPosition("");
                  setStatus("");
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
      {importOpen && (
        <StatusImportModal onClose={() => setImportOpen(false)} onSaved={load} />
      )}
    </div>
  );
}
