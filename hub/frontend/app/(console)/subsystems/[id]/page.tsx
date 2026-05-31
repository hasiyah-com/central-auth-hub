"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge } from "@/components/Badge";
import { clientFetch } from "@/lib/api";

// ── Types ──────────────────────────────────────────────────
type Subsystem = {
  id: string;
  name: string;
  description?: string;
  client_id: string;
  status: string;
  // scope ใน DB เป็น text[] → JSON เป็น array (ไม่ใช่ string!)
  scope?: string[] | string | null;
  whitelist_count: number;
  owner_email?: string;
  redirect_uris?: string[];
  created_at?: string;
  approved_at?: string;
};

type WhitelistEntry = {
  user_id: string;
  email: string;
  full_name?: string;
  user_type?: string;
  role_in_sub?: string;
  granted_at?: string;
};

type WhitelistResponse = {
  subsystem: string;
  total: number;
  users: WhitelistEntry[];
};

type AuditItem = {
  id: string;
  actor_id: string | null;
  actor_email: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  ip: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string | null;
};

const STATUS_TONE: Record<string, "good" | "warn" | "danger" | "default"> = {
  active: "good",
  pending: "warn",
  suspended: "danger",
};

// ── Helper: normalize scope ──────────────────────────────
function scopeList(scope: Subsystem["scope"]): string[] {
  if (!scope) return [];
  if (Array.isArray(scope)) return scope;
  // legacy: space-separated string
  return String(scope).split(/[\s,]+/).filter(Boolean);
}

export default function SubsystemDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const id = params.id;
  const [sub, setSub] = useState<Subsystem | null>(null);
  const [whitelist, setWhitelist] = useState<WhitelistEntry[] | null>(null);
  const [whitelistError, setWhitelistError] = useState<string | null>(null);
  const [audit, setAudit] = useState<AuditItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [newEmail, setNewEmail] = useState("");
  const [newRole, setNewRole] = useState("user");
  const [busyAdd, setBusyAdd] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(
    null
  );

  const loadSubsystem = useCallback(() => {
    clientFetch<Subsystem[]>(`/admin/subsystems`)
      .then((list) => {
        const found = list.find((s) => s.id === id) || null;
        setSub(found);
        if (!found) setError("ไม่พบ subsystem นี้");
      })
      .catch((e) => setError(e.detail || "โหลด subsystem ไม่สำเร็จ"));
  }, [id]);

  const loadWhitelist = useCallback(() => {
    setWhitelistError(null);
    clientFetch<WhitelistResponse>(
      `/developer/subsystems/${id}/whitelist`
    )
      .then((d) => setWhitelist(d.users || []))
      .catch((e) => {
        setWhitelist([]);
        // ปัจจุบัน endpoint เช็ค owner_user_id == current user
        // admin ที่ไม่ใช่ owner ของ subsystem นี้ → 404
        const detail = (e as { detail?: string }).detail || "";
        setWhitelistError(
          detail.includes("ไม่ใช่เจ้าของ") || detail.includes("ไม่พบ")
            ? "ดู whitelist ไม่ได้ — endpoint /developer/* จำกัดเฉพาะเจ้าของ subsystem"
            : detail
        );
      });
  }, [id]);

  const loadAudit = useCallback(() => {
    clientFetch<{ items: AuditItem[] }>(
      `/admin/audit?target_type=subsystem&limit=50`
    )
      .then((d) => {
        const filtered = (d.items || []).filter((a) => a.target_id === id);
        setAudit(filtered);
      })
      .catch(() => setAudit([]));
  }, [id]);

  useEffect(() => {
    loadSubsystem();
    loadWhitelist();
    loadAudit();
  }, [loadSubsystem, loadWhitelist, loadAudit]);

  async function addUser(e: React.FormEvent) {
    e.preventDefault();
    if (!newEmail.trim()) return;
    setBusyAdd(true);
    setMsg(null);
    try {
      await clientFetch(`/developer/subsystems/${id}/whitelist/user`, {
        method: "POST",
        body: JSON.stringify({ email: newEmail.trim(), role_in_sub: newRole }),
      });
      setMsg({ kind: "ok", text: `เพิ่ม ${newEmail} เข้า whitelist แล้ว` });
      setNewEmail("");
      loadWhitelist();
      loadAudit();
    } catch (e) {
      const err = e as { detail?: string };
      setMsg({ kind: "err", text: err.detail || "เพิ่มไม่สำเร็จ" });
    } finally {
      setBusyAdd(false);
    }
  }

  async function removeUser(userId: string, email: string) {
    if (!confirm(`ลบ ${email} ออกจาก whitelist?`)) return;
    setMsg(null);
    try {
      await clientFetch(`/developer/subsystems/${id}/whitelist/${userId}`, {
        method: "DELETE",
      });
      setMsg({ kind: "ok", text: `ลบ ${email} แล้ว (soft delete)` });
      loadWhitelist();
      loadAudit();
    } catch (e) {
      const err = e as { detail?: string };
      setMsg({ kind: "err", text: err.detail || "ลบไม่สำเร็จ" });
    }
  }

  if (error) {
    return (
      <>
        <Topbar title="Subsystem" />
        <main className="p-8 max-w-3xl mx-auto">
          <div className="p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm mb-4">
            {error}
          </div>
          <Link
            href="/subsystems"
            className="inline-block px-4 py-2 rounded-lg bg-ink-900 text-white text-sm hover:bg-ink-800"
          >
            ← กลับไปหน้ารายการ
          </Link>
        </main>
      </>
    );
  }

  if (!sub) {
    return (
      <>
        <Topbar title="Subsystem" />
        <main className="p-8 max-w-3xl mx-auto">
          <div className="text-ink-400 text-sm">กำลังโหลด…</div>
        </main>
      </>
    );
  }

  const scopes = scopeList(sub.scope);

  // ── Tables ──────────────────────────────────────────────
  const wlCols: Column<WhitelistEntry & Record<string, unknown>>[] = [
    {
      key: "full_name",
      header: "ผู้ใช้",
      render: (u) => (
        <div>
          <div className="font-semibold text-ink-900">{u.full_name || u.email}</div>
          <div className="text-[11px] text-ink-500 font-mono">{u.email}</div>
        </div>
      ),
    },
    {
      key: "user_type",
      header: "Type",
      width: "110px",
      render: (u) => (
        <Badge tone={u.user_type === "admin" ? "danger" : "brand"}>
          {(u.user_type || "—").toUpperCase()}
        </Badge>
      ),
    },
    {
      key: "role_in_sub",
      header: "Role in sub",
      width: "120px",
      render: (u) => (
        <span className="font-mono text-xs">{u.role_in_sub || "user"}</span>
      ),
    },
    {
      key: "granted_at",
      header: "Granted",
      width: "140px",
      render: (u) => (
        <span className="font-mono text-[11px] text-ink-500">
          {u.granted_at ? new Date(u.granted_at).toISOString().slice(0, 10) : "—"}
        </span>
      ),
    },
    {
      key: "actions",
      header: "—",
      width: "110px",
      render: (u) => (
        <button
          onClick={() => removeUser(u.user_id, u.email)}
          className="px-3 py-1 rounded-md bg-rose-50 hover:bg-rose-100 text-rose-700 text-xs font-semibold border border-rose-200 transition"
        >
          ลบ
        </button>
      ),
    },
  ];

  const auditCols: Column<AuditItem & Record<string, unknown>>[] = [
    {
      key: "created_at",
      header: "เวลา",
      width: "170px",
      render: (a) => (
        <span className="font-mono text-[11px] text-ink-500">
          {a.created_at
            ? new Date(a.created_at).toISOString().slice(0, 19).replace("T", " ")
            : "—"}
        </span>
      ),
    },
    {
      key: "action",
      header: "Action",
      render: (a) => (
        <span className="font-mono text-xs font-semibold text-ink-900">
          {a.action}
        </span>
      ),
    },
    {
      key: "actor_email",
      header: "ผู้กระทำ",
      render: (a) => (
        <span className="text-xs text-ink-700">{a.actor_email || "—"}</span>
      ),
    },
    {
      key: "ip",
      header: "IP",
      width: "130px",
      render: (a) => (
        <span className="font-mono text-[11px] text-ink-500">{a.ip || "—"}</span>
      ),
    },
  ];

  return (
    <>
      <Topbar title={sub.name} />
      <main className="p-8 max-w-7xl mx-auto w-full space-y-6">
        {/* Breadcrumb + status hero */}
        <div className="flex items-end justify-between gap-4 flex-wrap">
          <div>
            <Link
              href="/subsystems"
              className="text-xs text-ink-500 hover:text-brand-600 underline"
            >
              ← กลับไป Subsystems
            </Link>
            <h2 className="mt-2 text-2xl font-extrabold text-ink-900">
              {sub.name}
            </h2>
            {sub.description && (
              <p className="mt-1 text-sm text-ink-500 max-w-2xl">
                {sub.description}
              </p>
            )}
          </div>
          <div className="flex flex-col items-end gap-2">
            <Badge tone={STATUS_TONE[sub.status] || "default"}>
              ● {sub.status.toUpperCase()}
            </Badge>
            <div className="text-[11px] text-ink-400 font-mono">
              {sub.created_at &&
                `สร้าง ${new Date(sub.created_at).toISOString().slice(0, 10)}`}
              {sub.approved_at &&
                ` · อนุมัติ ${new Date(sub.approved_at).toISOString().slice(0, 10)}`}
            </div>
          </div>
        </div>

        {msg && (
          <div
            className={
              "p-3 rounded-lg text-sm " +
              (msg.kind === "ok"
                ? "bg-emerald-50 border border-emerald-200 text-emerald-700"
                : "bg-rose-50 border border-rose-200 text-rose-700")
            }
          >
            {msg.text}
          </div>
        )}

        {/* ── Section 1: Identity card ───────────────────── */}
        <section>
          <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
            ข้อมูล OAuth Client
          </h3>
          <div className="bg-white rounded-xl border border-ink-200 shadow-sm p-6 grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-5">
            <Field label="Client ID" mono value={sub.client_id} />
            <Field label="เจ้าของ" value={sub.owner_email || "—"} />

            <div>
              <FieldLabel>Scope (OAuth)</FieldLabel>
              {scopes.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {scopes.map((s) => (
                    <span
                      key={s}
                      className="px-2 py-0.5 rounded bg-brand-50 text-brand-700 text-[11px] font-mono font-semibold border border-brand-100"
                    >
                      {s}
                    </span>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-ink-400">—</div>
              )}
            </div>

            <div>
              <FieldLabel>จำนวน Whitelist</FieldLabel>
              <div className="text-2xl font-extrabold text-ink-900 tabular-nums">
                {sub.whitelist_count}
                <span className="ml-1 text-xs font-normal text-ink-400">คน</span>
              </div>
            </div>

            <div className="md:col-span-2">
              <FieldLabel>Redirect URIs</FieldLabel>
              {sub.redirect_uris && sub.redirect_uris.length > 0 ? (
                <ul className="space-y-1.5">
                  {sub.redirect_uris.map((u) => (
                    <li
                      key={u}
                      className="font-mono text-[12px] text-ink-700 bg-ink-50 px-3 py-2 rounded border border-ink-100 break-all"
                    >
                      {u}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="text-sm text-ink-400">
                  ยังไม่ได้ลงทะเบียน redirect URI
                </div>
              )}
            </div>
          </div>
        </section>

        {/* ── Section 2: Whitelist ───────────────────────── */}
        <section>
          <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
            Whitelist · ผู้ใช้ที่มีสิทธิ์เข้า subsystem นี้
          </h3>

          {whitelistError && (
            <div className="mb-3 p-3 rounded-lg bg-amber-50 border border-amber-200 text-amber-800 text-xs">
              ⚠ {whitelistError}
            </div>
          )}

          {/* Add form */}
          <form
            onSubmit={addUser}
            className="mb-3 bg-white rounded-xl border border-ink-200 shadow-sm p-4 flex flex-wrap items-end gap-3"
          >
            <div className="flex-1 min-w-[220px]">
              <FieldLabel>เพิ่ม user (อีเมล)</FieldLabel>
              <input
                type="email"
                placeholder="user@uni.ac.th"
                value={newEmail}
                onChange={(e) => setNewEmail(e.target.value)}
                required
                className="w-full px-3 py-2 rounded-lg border border-ink-200 bg-white text-sm focus:outline-none focus:border-brand-500"
              />
            </div>
            <div>
              <FieldLabel>Role in subsystem</FieldLabel>
              <select
                value={newRole}
                onChange={(e) => setNewRole(e.target.value)}
                className="px-3 py-2 rounded-lg border border-ink-200 bg-white text-sm focus:outline-none focus:border-brand-500"
              >
                <option value="user">user</option>
                <option value="staff">staff</option>
                <option value="admin">admin</option>
              </select>
            </div>
            <button
              type="submit"
              disabled={busyAdd}
              className="px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-700 text-white text-sm font-semibold disabled:opacity-50 transition"
            >
              {busyAdd ? "กำลังเพิ่ม…" : "+ เพิ่มเข้า whitelist"}
            </button>
          </form>

          <DataTable
            columns={wlCols}
            rows={
              (whitelist || []) as Array<WhitelistEntry & Record<string, unknown>>
            }
            emptyMessage={
              whitelistError ? "ไม่มีข้อมูลที่แสดงได้" : "ยังไม่มี user ใน whitelist"
            }
          />
        </section>

        {/* ── Section 3: Activity ────────────────────────── */}
        <section>
          <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
            Audit · กิจกรรมที่เกิดกับ subsystem นี้
          </h3>
          <DataTable
            columns={auditCols}
            rows={(audit || []) as Array<AuditItem & Record<string, unknown>>}
            emptyMessage="ไม่มี activity"
          />
        </section>

        <div className="pt-4 text-center text-[11px] text-ink-400 font-mono">
          subsystem_id: {sub.id}
        </div>
      </main>
    </>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[11px] font-bold text-ink-500 uppercase tracking-wider mb-1.5">
      {children}
    </div>
  );
}

function Field({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <FieldLabel>{label}</FieldLabel>
      <div
        className={
          mono
            ? "font-mono text-[13px] text-ink-900 break-all bg-ink-50 px-3 py-2 rounded border border-ink-100"
            : "text-sm text-ink-900"
        }
      >
        {value}
      </div>
    </div>
  );
}
