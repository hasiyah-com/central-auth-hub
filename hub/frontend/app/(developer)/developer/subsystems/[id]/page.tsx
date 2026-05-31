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
  created_at: string;
};

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
  }, [loadSubsystem, loadWhitelist]);

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
      width: "140px",
      render: (u) => (
        <span className="font-mono text-xs">{u.role_in_sub || "member"}</span>
      ),
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
            <div className="text-[11px] text-ink-400 font-mono">
              ลงทะเบียน{" "}
              {new Date(sub.created_at).toISOString().slice(0, 10)}
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
                <option value="member">member</option>
                <option value="resident">resident</option>
                <option value="staff">staff</option>
                <option value="admin">admin</option>
              </select>
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
