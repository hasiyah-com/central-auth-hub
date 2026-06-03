"use client";

import { useEffect, useState, useCallback, useRef } from "react";
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
  allowed_roles?: string[];
  redirect_uris?: string[];
  access_revoke_webhook_url?: string | null;
  previous_secret_expires_at?: string | null;
  created_at: string;
};

type PendingRequest = {
  id: string;
  request_type: string;
  payload: Record<string, unknown>;
  status: string;
  created_at: string | null;
};

const PENDING_TYPE_LABEL: Record<string, string> = {
  rotate_secret: "🔑 Rotate Secret",
  edit_scope: "🎯 แก้ Scope",
  edit_allowed_roles: "🧰 แก้ Allowed Roles",
  edit_redirect_uris: "↩️ แก้ Redirect URIs",
  change_whitelist_role: "👤 เปลี่ยน role (1 คน)",
  bulk_change_whitelist_roles: "👥 เปลี่ยน role (batch)",
};

const SCOPE_OPTIONS: Array<{ key: string; label: string; desc: string }> = [
  { key: "email", label: "Email", desc: "อีเมลของผู้ใช้" },
  { key: "name", label: "Full Name", desc: "ชื่อ-นามสกุล" },
  { key: "student_id", label: "Student ID", desc: "รหัสนักศึกษา" },
  { key: "employee_id", label: "Employee ID", desc: "รหัสบุคลากร" },
  { key: "faculty", label: "Faculty", desc: "คณะ" },
  { key: "major", label: "Major", desc: "สาขาวิชา" },
  { key: "year", label: "Year", desc: "ชั้นปี" },
  { key: "position", label: "Position", desc: "ตำแหน่ง" },
  { key: "phone", label: "Phone", desc: "เบอร์โทร" },
  { key: "address", label: "Address", desc: "ที่อยู่" },
];

type WhitelistEntry = {
  user_id: string;
  email: string;
  full_name?: string;
  role_in_sub?: string;
  granted_at?: string;
};

type WhitelistResponse = {
  subsystem: string;
  total: number;
  users: WhitelistEntry[];
};

type CsvUploadResponse = {
  subsystem: string;
  added: number;
  skipped: number;
  added_emails: string[];
  skipped_details: Array<{ email: string; reason: string }>;
};

const STATUS_TONE: Record<string, "good" | "warn" | "danger" | "default"> = {
  active: "good",
  pending: "warn",
  suspended: "danger",
};

export default function DeveloperSubsystemDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const id = params.id;

  const [sub, setSub] = useState<Subsystem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [whitelist, setWhitelist] = useState<WhitelistEntry[]>([]);
  const [whitelistError, setWhitelistError] = useState<string | null>(null);

  const [newEmail, setNewEmail] = useState("");
  const [newRole, setNewRole] = useState("member");
  const [busyAdd, setBusyAdd] = useState(false);

  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(
    null
  );

  const [csvResult, setCsvResult] = useState<CsvUploadResponse | null>(null);
  const [csvUploading, setCsvUploading] = useState(false);
  const csvInputRef = useRef<HTMLInputElement>(null);

  // Rotate secret
  const [rotateBusy, setRotateBusy] = useState(false);
  // Edit modal
  const [editOpen, setEditOpen] = useState(false);
  const [editDesc, setEditDesc] = useState("");
  const [editRedirects, setEditRedirects] = useState("");
  const [editScope, setEditScope] = useState<Set<string>>(new Set());
  const [editAllowedRoles, setEditAllowedRoles] = useState("");
  const [editBusy, setEditBusy] = useState(false);
  // Pending requests for this subsystem
  const [pendings, setPendings] = useState<PendingRequest[]>([]);
  // Inline role editing per user
  const [editingRoleFor, setEditingRoleFor] = useState<string | null>(null);
  const [editingRoleValue, setEditingRoleValue] = useState("");

  function startEditRole(u: WhitelistEntry) {
    setEditingRoleFor(u.user_id);
    setEditingRoleValue(u.role_in_sub || "user");
  }
  function cancelEditRole() {
    setEditingRoleFor(null);
    setEditingRoleValue("");
  }
  async function saveRole(userId: string, email: string) {
    if (!editingRoleValue.trim()) return;
    setMsg(null);
    try {
      const r = await clientFetch<{ result: string }>(
        `/developer/subsystems/${id}/whitelist/${userId}`,
        {
          method: "PATCH",
          body: JSON.stringify({ role_in_sub: editingRoleValue.trim() }),
        }
      );
      setMsg({ kind: "ok", text: `${email}: ${r.result}` });
      cancelEditRole();
      loadWhitelist();
    } catch (e) {
      const err = e as { detail?: string };
      setMsg({ kind: "err", text: err.detail || "เปลี่ยน role ไม่สำเร็จ" });
    }
  }

  function toggleEditScope(key: string) {
    setEditScope((s) => {
      const next = new Set(s);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const loadPendings = useCallback(() => {
    clientFetch<{ items: PendingRequest[] }>(
      `/developer/subsystems/${id}/change-requests?status=pending`
    )
      .then((d) => setPendings(d.items || []))
      .catch(() => setPendings([]));
  }, [id]);

  async function rotateSecret() {
    if (
      !confirm(
        "ขอ rotate client_secret?\n\nระบบจะสร้าง pending request — admin ต้อง approve ก่อน\nหลัง approve คุณจะได้รับ email พร้อมลิงก์ดู secret ใหม่"
      )
    )
      return;
    setRotateBusy(true);
    setMsg(null);
    try {
      const r = await clientFetch<{ message: string }>(
        `/developer/subsystems/${id}/rotate-secret`,
        { method: "POST" }
      );
      setMsg({ kind: "ok", text: r.message });
      loadPendings();
    } catch (e) {
      const err = e as { detail?: string };
      setMsg({ kind: "err", text: err.detail || "rotate ไม่สำเร็จ" });
    } finally {
      setRotateBusy(false);
    }
  }

  function openEditModal() {
    if (!sub) return;
    setEditDesc(sub.description || "");
    setEditRedirects((sub.redirect_uris || []).join("\n"));
    setEditScope(new Set(sub.scope || []));
    setEditAllowedRoles((sub.allowed_roles || []).join(", "));
    setEditOpen(true);
  }

  async function saveEdit() {
    if (!sub) return;
    setEditBusy(true);
    setMsg(null);
    const body: Record<string, unknown> = {};

    if (editDesc !== (sub.description || "")) body.description = editDesc;

    const newRedirects = editRedirects
      .split(/\n+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (
      JSON.stringify(newRedirects) !==
      JSON.stringify(sub.redirect_uris || [])
    ) {
      body.redirect_uris = newRedirects;
    }

    const newScope = Array.from(editScope);
    if (
      JSON.stringify(newScope.slice().sort()) !==
      JSON.stringify((sub.scope || []).slice().sort())
    ) {
      body.scope = newScope;
    }

    const newRoles = editAllowedRoles
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (
      JSON.stringify(newRoles) !== JSON.stringify(sub.allowed_roles || [])
    ) {
      body.allowed_roles = newRoles;
    }

    if (Object.keys(body).length === 0) {
      setMsg({ kind: "ok", text: "ไม่มีการเปลี่ยนแปลง" });
      setEditOpen(false);
      setEditBusy(false);
      return;
    }

    try {
      const r = await clientFetch<{
        result: string;
        pending_requests?: Array<{ label: string }>;
      }>(`/developer/subsystems/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      setMsg({
        kind: "ok",
        text: r.result + (r.pending_requests?.length ? " — รอ admin review" : ""),
      });
      setEditOpen(false);
      loadSubsystem();
      loadPendings();
    } catch (e) {
      const err = e as { detail?: string };
      setMsg({ kind: "err", text: err.detail || "บันทึกไม่สำเร็จ" });
    } finally {
      setEditBusy(false);
    }
  }

  const loadSubsystem = useCallback(() => {
    clientFetch<Subsystem[]>("/developer/subsystems")
      .then((list) => {
        const found = list.find((s) => s.id === id) || null;
        setSub(found);
        if (!found) setError("ไม่พบระบบนี้ — หรือคุณไม่ใช่เจ้าของ");
      })
      .catch((e) => setError(e.detail || "โหลดข้อมูลไม่สำเร็จ"));
  }, [id]);

  const loadWhitelist = useCallback(() => {
    setWhitelistError(null);
    clientFetch<WhitelistResponse>(`/developer/subsystems/${id}/whitelist`)
      .then((d) => setWhitelist(d.users || []))
      .catch((e) => {
        setWhitelist([]);
        setWhitelistError(e.detail || "โหลด whitelist ไม่สำเร็จ");
      });
  }, [id]);

  useEffect(() => {
    loadSubsystem();
    loadWhitelist();
    loadPendings();
  }, [loadSubsystem, loadWhitelist, loadPendings]);

  // Sync newRole กับ allowed_roles ของ subsystem
  useEffect(() => {
    if (sub?.allowed_roles?.length) {
      if (!sub.allowed_roles.includes(newRole)) {
        setNewRole(sub.allowed_roles[0]);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sub]);

  async function addUser(e: React.FormEvent) {
    e.preventDefault();
    if (!newEmail.trim()) return;
    setBusyAdd(true);
    setMsg(null);
    try {
      await clientFetch(`/developer/subsystems/${id}/whitelist/user`, {
        method: "POST",
        body: JSON.stringify({ email: newEmail.trim(), role: newRole }),
      });
      setMsg({ kind: "ok", text: `เพิ่ม ${newEmail} เข้า whitelist แล้ว` });
      setNewEmail("");
      loadWhitelist();
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
    } catch (e) {
      const err = e as { detail?: string };
      setMsg({ kind: "err", text: err.detail || "ลบไม่สำเร็จ" });
    }
  }

  async function uploadCsv(file: File) {
    setCsvUploading(true);
    setCsvResult(null);
    setMsg(null);
    try {
      const form = new FormData();
      form.append("file", file);
      // FormData → ใช้ /api/proxy ตรง (clientFetch บังคับ JSON header)
      const res = await fetch(
        `/api/proxy/developer/subsystems/${id}/whitelist`,
        {
          method: "POST",
          credentials: "include",
          body: form,
        }
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Upload failed: ${res.status}`);
      }
      const data = (await res.json()) as CsvUploadResponse;
      setCsvResult(data);
      setMsg({
        kind: "ok",
        text: `Upload เสร็จ — เพิ่ม ${data.added} คน, ข้าม ${data.skipped} คน`,
      });
      loadWhitelist();
    } catch (e) {
      const err = e as { message?: string };
      setMsg({
        kind: "err",
        text: err.message || "Upload CSV ไม่สำเร็จ",
      });
    } finally {
      setCsvUploading(false);
      if (csvInputRef.current) csvInputRef.current.value = "";
    }
  }

  if (error) {
    return (
      <>
        <Topbar title="ระบบย่อย" />
        <main className="p-8 max-w-3xl mx-auto">
          <div className="p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm mb-4">
            {error}
          </div>
          <Link
            href="/developer/subsystems"
            className="inline-block px-4 py-2 rounded-lg bg-ink-900 text-white text-sm"
          >
            ← กลับรายการ
          </Link>
        </main>
      </>
    );
  }

  if (!sub) {
    return (
      <>
        <Topbar title="ระบบย่อย" />
        <main className="p-8 max-w-3xl mx-auto text-ink-400 text-sm">
          กำลังโหลด…
        </main>
      </>
    );
  }

  // ── Whitelist table columns ──────────────────────────────
  const wlCols: Column<WhitelistEntry & Record<string, unknown>>[] = [
    {
      key: "full_name",
      header: "ผู้ใช้",
      render: (u) => (
        <div>
          <div className="font-semibold text-ink-900">
            {u.full_name || u.email}
          </div>
          <div className="text-[11px] text-ink-500 font-mono">{u.email}</div>
        </div>
      ),
    },
    {
      key: "role_in_sub",
      header: "Role in sub",
      width: "180px",
      render: (u) => {
        if (editingRoleFor === u.user_id) {
          const allowed =
            sub?.allowed_roles && sub.allowed_roles.length > 0
              ? sub.allowed_roles
              : ["user"];
          return (
            <div className="flex items-center gap-1">
              <select
                value={editingRoleValue}
                onChange={(e) => setEditingRoleValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") saveRole(u.user_id, u.email);
                  if (e.key === "Escape") cancelEditRole();
                }}
                autoFocus
                className="px-2 py-1 rounded border border-brand-300 text-xs font-mono focus:outline-none focus:border-brand-500"
              >
                {allowed.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
              <button
                onClick={() => saveRole(u.user_id, u.email)}
                className="px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-[11px] font-semibold"
                title="บันทึก (Enter)"
              >
                ✓
              </button>
              <button
                onClick={cancelEditRole}
                className="px-2 py-1 rounded bg-ink-200 hover:bg-ink-300 text-ink-700 text-[11px] font-semibold"
                title="ยกเลิก (Esc)"
              >
                ✕
              </button>
            </div>
          );
        }
        return (
          <button
            onClick={() => startEditRole(u)}
            className="font-mono text-xs px-2 py-0.5 rounded hover:bg-ink-100 cursor-pointer text-ink-900"
            title="คลิกเพื่อแก้ role"
          >
            {u.role_in_sub || "user"} <span className="text-ink-400">✎</span>
          </button>
        );
      },
    },
    {
      key: "granted_at",
      header: "เพิ่มเมื่อ",
      width: "140px",
      render: (u) => (
        <span className="font-mono text-[11px] text-ink-500">
          {u.granted_at
            ? new Date(u.granted_at).toISOString().slice(0, 10)
            : "—"}
        </span>
      ),
    },
    {
      key: "actions",
      header: "—",
      width: "100px",
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

  return (
    <>
      <Topbar title={sub.name} />
      <main className="p-8 max-w-7xl mx-auto w-full space-y-6">
        {/* Header */}
        <div className="flex items-end justify-between gap-4 flex-wrap">
          <div>
            <Link
              href="/developer/subsystems"
              className="text-xs text-ink-500 hover:text-brand-600 underline"
            >
              ← กลับไป Developer Portal
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
            <div className="flex flex-wrap gap-2 justify-end">
              <button
                onClick={openEditModal}
                className="px-3 py-1.5 rounded-lg border border-ink-200 hover:bg-ink-50 text-xs font-semibold text-ink-700 transition"
              >
                ✎ แก้ไข
              </button>
              <button
                onClick={rotateSecret}
                disabled={rotateBusy}
                className="px-3 py-1.5 rounded-lg border border-amber-200 hover:bg-amber-50 text-xs font-semibold text-amber-700 disabled:opacity-50 transition"
                title="ขอ rotate client_secret (admin ต้อง approve)"
              >
                {rotateBusy ? "…" : "🔑 ขอ Rotate Secret"}
              </button>
            </div>
            <div className="text-[11px] text-ink-400 font-mono">
              ลงทะเบียน{" "}
              {new Date(sub.created_at).toISOString().slice(0, 10)}
            </div>
          </div>
        </div>

        {/* Pending change requests banner */}
        {pendings.length > 0 && (
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
            <div className="text-xs font-bold text-amber-900 uppercase tracking-wider mb-2">
              ⏳ Pending Approval · {pendings.length} request
            </div>
            <ul className="space-y-1 text-sm">
              {pendings.map((p) => (
                <li key={p.id} className="text-amber-800">
                  <span className="font-semibold">
                    {PENDING_TYPE_LABEL[p.request_type] || p.request_type}
                  </span>
                  {p.created_at && (
                    <span className="text-[11px] text-amber-600 ml-2 font-mono">
                      {new Date(p.created_at).toISOString().slice(0, 16).replace("T", " ")}
                    </span>
                  )}
                </li>
              ))}
            </ul>
            <div className="mt-2 text-[11px] text-amber-700">
              admin จะ review และส่ง email แจ้งผลให้คุณ
            </div>
          </div>
        )}

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

        {/* Identity card */}
        <section>
          <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
            ข้อมูล OAuth Client
          </h3>
          <div className="bg-white rounded-xl border border-ink-200 shadow-sm p-6 grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-5">
            <div>
              <FieldLabel>Client ID</FieldLabel>
              <div className="font-mono text-[13px] text-ink-900 break-all bg-ink-50 px-3 py-2 rounded border border-ink-100">
                {sub.client_id}
              </div>
            </div>
            <div>
              <FieldLabel>Client Secret</FieldLabel>
              <div className="text-sm text-ink-400 italic">
                ส่งให้คุณทางอีเมลตอนลงทะเบียน — หากลืม ต้องลงทะเบียนระบบใหม่
              </div>
            </div>

            <div className="md:col-span-2">
              <FieldLabel>Scope</FieldLabel>
              <div className="flex flex-wrap gap-1.5">
                {sub.scope.map((s) => (
                  <span
                    key={s}
                    className="px-2 py-0.5 rounded bg-brand-50 text-brand-700 text-[11px] font-mono font-semibold border border-brand-100"
                  >
                    {s}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* Whitelist */}
        <section>
          <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
            Whitelist · ผู้ใช้ที่อนุญาตให้เข้า subsystem นี้
          </h3>

          {whitelistError && (
            <div className="mb-3 p-3 rounded-lg bg-amber-50 border border-amber-200 text-amber-800 text-xs">
              ⚠ {whitelistError}
            </div>
          )}

          {/* Add user form */}
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
                className="w-full px-3 py-2 rounded-lg border border-ink-200 focus:outline-none focus:border-brand-500 text-sm"
              />
            </div>
            <div>
              <FieldLabel>Role in sub</FieldLabel>
              <select
                value={newRole}
                onChange={(e) => setNewRole(e.target.value)}
                className="px-3 py-2 rounded-lg border border-ink-200 focus:outline-none focus:border-brand-500 text-sm"
              >
                {(sub.allowed_roles && sub.allowed_roles.length > 0
                  ? sub.allowed_roles
                  : ["user"]
                ).map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
              <div className="text-[10px] text-ink-400 mt-1">
                ระบบรับ: {(sub.allowed_roles || ["user"]).join(", ")}
              </div>
            </div>
            <button
              type="submit"
              disabled={busyAdd}
              className="px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-700 text-white text-sm font-semibold disabled:opacity-50 transition"
            >
              {busyAdd ? "กำลังเพิ่ม…" : "+ เพิ่ม"}
            </button>
          </form>

          {/* CSV upload */}
          <div className="mb-3 bg-white rounded-xl border border-dashed border-ink-300 p-4 flex flex-wrap items-center gap-3">
            <div className="flex-1 min-w-[200px]">
              <div className="text-xs font-bold text-ink-700">
                📄 อัปโหลด CSV (bulk add)
              </div>
              <div className="text-[11px] text-ink-500 mt-0.5">
                CSV header: <code className="font-mono">email,role,note</code> —
                ระบบ skip คนที่ไม่อยู่ใน Hub
              </div>
            </div>
            <input
              ref={csvInputRef}
              type="file"
              accept=".csv"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) uploadCsv(f);
              }}
              disabled={csvUploading}
              className="text-xs"
            />
            {csvUploading && (
              <span className="text-xs text-ink-500 animate-pulse">
                กำลังอัปโหลด…
              </span>
            )}
          </div>

          {csvResult && (
            <div className="mb-3 p-4 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm">
              <div className="font-semibold mb-1">
                ✓ Upload สำเร็จ — เพิ่ม {csvResult.added} คน, ข้าม{" "}
                {csvResult.skipped} คน
              </div>
              {csvResult.skipped_details.length > 0 && (
                <details className="mt-2 text-xs">
                  <summary className="cursor-pointer hover:underline">
                    ดูรายละเอียดที่ข้าม
                  </summary>
                  <ul className="mt-2 space-y-1 ml-4 list-disc">
                    {csvResult.skipped_details.map((d, i) => (
                      <li key={i}>
                        <span className="font-mono">{d.email}</span> — {d.reason}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}

          <DataTable
            columns={wlCols}
            rows={
              whitelist as Array<WhitelistEntry & Record<string, unknown>>
            }
            emptyMessage="ยังไม่มี user ใน whitelist"
          />
        </section>

        <div className="pt-4 text-center text-[11px] text-ink-400 font-mono">
          subsystem_id: {sub.id}
        </div>
      </main>

      {/* Edit modal */}
      {editOpen && (
        <div
          className="fixed inset-0 bg-ink-900/40 z-50 flex items-center justify-center p-4"
          onClick={() => !editBusy && setEditOpen(false)}
        >
          <div
            className="bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-6 py-4 border-b border-ink-100 flex items-center justify-between">
              <h3 className="text-lg font-extrabold text-ink-900">
                แก้ไข Subsystem
              </h3>
              <button
                onClick={() => setEditOpen(false)}
                className="text-ink-400 hover:text-ink-700 text-xl"
              >
                ✕
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3">
                ⚠ <strong>การแก้ Scope, Allowed Roles, Redirect URIs</strong>{" "}
                ต้องผ่านการ approve จาก admin ก่อนถึงจะ apply จริง
                (description apply ได้ทันที)
              </div>

              <div>
                <div className="text-[11px] font-bold text-ink-500 uppercase tracking-wider mb-1.5">
                  คำอธิบาย <span className="text-emerald-600 normal-case">· apply ทันที</span>
                </div>
                <textarea
                  value={editDesc}
                  onChange={(e) => setEditDesc(e.target.value)}
                  rows={2}
                  className="w-full px-3 py-2 rounded-lg border border-ink-200 text-sm focus:outline-none focus:border-brand-500"
                />
              </div>

              <div>
                <div className="text-[11px] font-bold text-ink-500 uppercase tracking-wider mb-1.5">
                  Redirect URIs (1 บรรทัด/URL) <span className="text-amber-700 normal-case">· ต้อง approve</span>
                </div>
                <textarea
                  value={editRedirects}
                  onChange={(e) => setEditRedirects(e.target.value)}
                  rows={3}
                  className="w-full px-3 py-2 rounded-lg border border-ink-200 font-mono text-[12px] focus:outline-none focus:border-brand-500"
                />
              </div>

              <div>
                <div className="text-[11px] font-bold text-ink-500 uppercase tracking-wider mb-1.5">
                  Scope <span className="text-amber-700 normal-case">· ต้อง approve</span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {SCOPE_OPTIONS.map((s) => {
                    const checked = editScope.has(s.key);
                    return (
                      <label
                        key={s.key}
                        className={
                          "flex items-start gap-2 p-2 rounded-lg border cursor-pointer transition text-xs " +
                          (checked
                            ? "bg-brand-50 border-brand-300"
                            : "bg-white border-ink-200 hover:border-brand-200")
                        }
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleEditScope(s.key)}
                          className="mt-0.5 accent-brand-600"
                        />
                        <div>
                          <div className="text-[12px] font-semibold text-ink-900">
                            {s.label}{" "}
                            <span className="font-mono text-[10px] text-ink-400">
                              {s.key}
                            </span>
                          </div>
                          <div className="text-[10px] text-ink-500">
                            {s.desc}
                          </div>
                        </div>
                      </label>
                    );
                  })}
                </div>
              </div>

              <div>
                <div className="text-[11px] font-bold text-ink-500 uppercase tracking-wider mb-1.5">
                  Allowed Roles <span className="text-amber-700 normal-case">· ต้อง approve</span>
                </div>
                <input
                  value={editAllowedRoles}
                  onChange={(e) => setEditAllowedRoles(e.target.value)}
                  placeholder="resident, teacher, staff"
                  className="w-full px-3 py-2 rounded-lg border border-ink-200 font-mono text-[12px] focus:outline-none focus:border-brand-500"
                />
              </div>
            </div>
            <div className="px-6 py-4 border-t border-ink-100 flex justify-end gap-2">
              <button
                onClick={() => setEditOpen(false)}
                disabled={editBusy}
                className="px-4 py-2 rounded-lg border border-ink-200 hover:bg-ink-50 text-sm font-medium text-ink-700 disabled:opacity-50"
              >
                ยกเลิก
              </button>
              <button
                onClick={saveEdit}
                disabled={editBusy}
                className="px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-700 text-white text-sm font-semibold disabled:opacity-50"
              >
                {editBusy ? "กำลังบันทึก…" : "บันทึก"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[11px] font-bold uppercase tracking-wider text-ink-500 mb-1.5">
      {children}
    </div>
  );
}
