"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge } from "@/components/Badge";
import { LineChart } from "@/components/LineChart";
import { LatencyBandChart } from "@/components/LatencyBandChart";
import { clientFetch } from "@/lib/api";
import { mutateWithStepup, runWithStepup } from "@/lib/passkey";
import "@/app/signal-console.css";

function formatDuration(sec: number): string {
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem ? `${h}h ${rem}m` : `${h}h`;
}

function parseUTC(iso: string): Date {
  const hasTz = /[+-]\d{2}:?\d{2}$|Z$/i.test(iso);
  return new Date(hasTz ? iso : iso + "Z");
}

/** ดึงข้อความ error อ่านง่าย — รองรับ no_passkey + ยกเลิก Passkey */
function errText(e: unknown, fallback: string): string {
  if (e instanceof DOMException && e.name === "NotAllowedError")
    return "ยกเลิกการยืนยัน Passkey — ลองอีกครั้ง";
  const d = (e as { detail?: unknown })?.detail;
  if (typeof d === "string") return d;
  if (d && typeof d === "object" && (d as { code?: string }).code === "no_passkey")
    return "ต้องมี Passkey เพื่อยืนยัน — ตั้งค่าที่หน้าบัญชี/ความปลอดภัย หรือใช้ Account Recovery";
  return fallback;
}

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
  rotate_secret: "Rotate Secret", // pragma: allowlist secret
  edit_scope: "แก้ Scope",
  edit_allowed_roles: "แก้ Allowed Roles",
  edit_redirect_uris: "↩แก้ Redirect URIs",
  change_whitelist_role: "เปลี่ยน role (1 คน)",
  bulk_change_whitelist_roles: "เปลี่ยน role (batch)",
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

type StatsResponse = {
  subsystem: { id: string; name: string };
  range: { days: number; from: string; to: string };
  total_logins: number;
  unique_users: number;
  active_now: number;
  decision_breakdown: Record<string, number>;
  daily: Array<{ date: string; count: number }>;
};

type HealthPoint = {
  at?: string | null;
  status?: string | null;
  latency_ms?: number | null;
};

type HealthHistoryResponse = {
  points: HealthPoint[];
  count: number;
  avg_latency_ms: number | null;
  max_latency_ms: number | null;
  healthy_ratio: number | null;
  interval_sec: number;
};

type ActiveSession = {
  session_id: string;
  user_id: string | null;
  user_email: string | null;
  full_name: string | null;
  user_type: string | null;
  ip: string | null;
  geo_country: string | null;
  geo_city: string | null;
  browser: string | null;
  os_name: string | null;
  device_type: string | null;
  decision: string | null;
  login_at: string | null;
  session_expires_at: string | null;
  duration_sec: number;
};

type ActiveSessionsResponse = {
  subsystem: { id: string; name: string };
  count: number;
  sessions: ActiveSession[];
};

type AuditItem = {
  id: string;
  actor_id: string | null;
  actor_email: string | null;
  actor_user_type: string | null;
  actor_is_hub_admin: boolean;
  action: string;
  ip: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string | null;
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

  const [verifying, setVerifying] = useState(false);
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
      const r = await mutateWithStepup<{ result: string }>(
        `/developer/subsystems/${id}/whitelist/${userId}`,
        {
          method: "PATCH",
          body: JSON.stringify({ role_in_sub: editingRoleValue.trim() }),
        },
        setVerifying
      );
      setMsg({ kind: "ok", text: `${email}: ${r.result}` });
      cancelEditRole();
      loadWhitelist();
    } catch (e) {
      setMsg({ kind: "err", text: errText(e, "เปลี่ยน role ไม่สำเร็จ") });
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
      const r = await mutateWithStepup<{ message: string }>(
        `/developer/subsystems/${id}/rotate-secret`,
        { method: "POST" },
        setVerifying
      );
      setMsg({ kind: "ok", text: r.message });
      loadPendings();
    } catch (e) {
      setMsg({ kind: "err", text: errText(e, "rotate ไม่สำเร็จ") });
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
      const r = await mutateWithStepup<{
        result: string;
        pending_requests?: Array<{ label: string }>;
      }>(
        `/developer/subsystems/${id}`,
        {
          method: "PATCH",
          body: JSON.stringify(body),
        },
        setVerifying
      );
      setMsg({
        kind: "ok",
        text: r.result + (r.pending_requests?.length ? " — รอ admin review" : ""),
      });
      setEditOpen(false);
      loadSubsystem();
      loadPendings();
    } catch (e) {
      setMsg({ kind: "err", text: errText(e, "บันทึกไม่สำเร็จ") });
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

  // ── Insights (KPI / health / active sessions / audit) — owner-scoped ──
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [healthHist, setHealthHist] = useState<HealthHistoryResponse | null>(
    null
  );
  const [active, setActive] = useState<ActiveSessionsResponse | null>(null);
  const [audit, setAudit] = useState<AuditItem[] | null>(null);
  const [auditOffset, setAuditOffset] = useState(0);
  const [auditTotal, setAuditTotal] = useState(0);
  const AUDIT_PAGE = 50;

  const loadStats = useCallback(() => {
    clientFetch<StatsResponse>(`/developer/subsystems/${id}/stats?days=7`)
      .then(setStats)
      .catch(() => setStats(null));
  }, [id]);

  const loadHealthHistory = useCallback(() => {
    clientFetch<HealthHistoryResponse>(
      `/developer/subsystems/${id}/health-history`
    )
      .then(setHealthHist)
      .catch(() => setHealthHist(null));
  }, [id]);

  const loadActive = useCallback(() => {
    clientFetch<ActiveSessionsResponse>(
      `/developer/subsystems/${id}/active-sessions`
    )
      .then(setActive)
      .catch(() => setActive(null));
  }, [id]);

  const loadAudit = useCallback(
    (offset: number = 0) => {
      clientFetch<{ items: AuditItem[]; total: number }>(
        `/developer/subsystems/${id}/audit?skip=${offset}&limit=${AUDIT_PAGE}`
      )
        .then((d) => {
          setAudit(d.items || []);
          setAuditTotal(d.total || 0);
          setAuditOffset(offset);
        })
        .catch(() => {
          setAudit([]);
          setAuditTotal(0);
        });
    },
    [id]
  );

  useEffect(() => {
    loadSubsystem();
    loadWhitelist();
    loadPendings();
    loadStats();
    loadHealthHistory();
    loadActive();
    loadAudit(0);
  }, [
    loadSubsystem,
    loadWhitelist,
    loadPendings,
    loadStats,
    loadHealthHistory,
    loadActive,
    loadAudit,
  ]);

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
      await mutateWithStepup(
        `/developer/subsystems/${id}/whitelist/user`,
        {
          method: "POST",
          body: JSON.stringify({ email: newEmail.trim(), role: newRole }),
        },
        setVerifying
      );
      setMsg({ kind: "ok", text: `เพิ่ม ${newEmail} เข้า whitelist แล้ว` });
      setNewEmail("");
      loadWhitelist();
    } catch (e) {
      setMsg({ kind: "err", text: errText(e, "เพิ่มไม่สำเร็จ") });
    } finally {
      setBusyAdd(false);
    }
  }

  async function removeUser(userId: string, email: string) {
    if (!confirm(`ลบ ${email} ออกจาก whitelist?`)) return;
    setMsg(null);
    try {
      await mutateWithStepup(
        `/developer/subsystems/${id}/whitelist/${userId}`,
        { method: "DELETE" },
        setVerifying
      );
      setMsg({ kind: "ok", text: `ลบ ${email} แล้ว (soft delete)` });
      loadWhitelist();
    } catch (e) {
      setMsg({ kind: "err", text: errText(e, "ลบไม่สำเร็จ") });
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
      // ยังต้องผ่าน step-up gate เหมือน mutation อื่น — wrap ด้วย runWithStepup
      // เพื่อให้ 403 stepup_required เปิด popup ยืนยัน Passkey แทนที่จะโชว์ error ดิบ
      const data = await runWithStepup<CsvUploadResponse>(async () => {
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
          throw { status: res.status, detail: body.detail ?? `Upload failed: ${res.status}` };
        }
        return (await res.json()) as CsvUploadResponse;
      }, setVerifying);
      setCsvResult(data);
      setMsg({
        kind: "ok",
        text: `Upload เสร็จ — เพิ่ม ${data.added} คน, ข้าม ${data.skipped} คน`,
      });
      loadWhitelist();
    } catch (e) {
      setMsg({ kind: "err", text: errText(e, "Upload CSV ไม่สำเร็จ") });
    } finally {
      setCsvUploading(false);
      if (csvInputRef.current) csvInputRef.current.value = "";
    }
  }

  if (error) {
    return (
      <>
        <Topbar title="ระบบย่อย" />
        <div className="sc">
          <main className="cx-document">
            <div className="cx-msg err">{error}</div>
            <Link href="/developer/subsystems" className="cx-back">
              My Subsystems
            </Link>
          </main>
        </div>
      </>
    );
  }

  if (!sub) {
    return (
      <>
        <Topbar title="ระบบย่อย" />
        <div className="sc">
          <main className="cx-document text-ink-400 text-sm">กำลังโหลด…</main>
        </div>
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
                บันทึก
              </button>
              <button
                onClick={cancelEditRole}
                className="px-2 py-1 rounded bg-ink-200 hover:bg-ink-300 text-ink-700 text-[11px] font-semibold"
                title="ยกเลิก (Esc)"
              >
                ยกเลิก
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
            {u.role_in_sub || "user"}
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
      {verifying && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-2xl px-6 py-5 shadow-xl flex items-center gap-3 text-sm text-ink-700">
            กำลังยืนยันด้วย Passkey… ทำตามที่อุปกรณ์
          </div>
        </div>
      )}
      <Topbar title={sub.name} />
      <div className="sc">
      <section className="cx-command">
        <div>
          <span>
            <span className="cx-dot">
              <i />
            </span>
            developer portal
          </span>
          <h1>Subsystem Detail</h1>
        </div>
        <div className="cx-command-actions">
          <span
            className={`cx-hero-status${
              sub.status === "suspended"
                ? " danger"
                : sub.status === "pending"
                ? " warn"
                : ""
            }`}
          >
            {sub.status.toUpperCase()}
          </span>
          <button onClick={openEditModal} className="cx-hero-btn">
            แก้ไข
          </button>
          <button
            onClick={rotateSecret}
            disabled={rotateBusy}
            className="cx-hero-btn warn"
            title="ขอ rotate client_secret (admin ต้อง approve)"
          >
            {rotateBusy ? "…" : "ขอ Rotate Secret"}
          </button>
        </div>
      </section>

      <main className="cx-document">
        <Link href="/developer/subsystems" className="cx-back">
          My Subsystems
        </Link>

        {/* ── Hero identity ── */}
        <section className="cx-identity-hero">
          <div>
            <span>subsystem</span>
            <h2>
              {sub.name}
              {sub.description && <small>{sub.description}</small>}
            </h2>
            <code>client_id · {sub.client_id}</code>
            {sub.created_at && (
              <span className="cx-hero-dates">
                ลงทะเบียน{" "}
                {new Date(sub.created_at).toISOString().slice(0, 10)}
              </span>
            )}
          </div>
          <div className="cx-hero-metrics">
            <span>
              whitelist
              <b>{whitelist.length}</b>
            </span>
            <span>
              scope
              <b>{sub.scope.length}</b>
            </span>
          </div>
        </section>

        {/* ── KPI 7 วัน + Daily Logins ── */}
        {stats && (
          <section>
            <div className="cx-kpis four">
              <KpiCard
                label="Login total"
                sub="7 วันล่าสุด"
                value={stats.total_logins.toLocaleString("en-US")}
                tone="brand"
              />
              <KpiCard
                label="Unique users"
                sub="7 วันล่าสุด"
                value={stats.unique_users.toLocaleString("en-US")}
                tone="default"
              />
              <KpiCard
                label="Active ตอนนี้"
                value={stats.active_now.toLocaleString("en-US")}
                tone={stats.active_now > 0 ? "good" : "default"}
              />
              <KpiCard
                label="Block / would_block"
                sub="7 วันล่าสุด"
                value={(
                  (stats.decision_breakdown.block || 0) +
                  (stats.decision_breakdown.would_block || 0)
                ).toLocaleString("en-US")}
                tone="danger"
              />
            </div>
            {stats.daily.length > 0 &&
              (() => {
                const max = Math.max(...stats.daily.map((x) => x.count), 1);
                return (
                  <section className="cx-panel">
                    <header>
                      <div>
                        <span>daily logins · 7 วัน</span>
                        <h2>Daily Logins</h2>
                      </div>
                      <span className="cx-chip mono">max {max}</span>
                    </header>
                    <div className="cx-panel-body">
                      <LineChart
                        labels={stats.daily.map((d) => d.date.slice(5))}
                        series={[
                          {
                            name: "Login",
                            color: "#6366f1",
                            values: stats.daily.map((d) => d.count),
                          },
                        ]}
                        height={170}
                        valueSuffix=" logins"
                      />
                    </div>
                  </section>
                );
              })()}
          </section>
        )}

        {/* ── Health — latency ย้อนหลัง (จากประวัติจริง) ── */}
        <section className="cx-panel">
          <header>
            <div>
              <span>health · ping ทุก 5 นาที</span>
              <h2>Health & Availability</h2>
            </div>
            <button onClick={loadHealthHistory} className="cx-refresh">
              refresh
            </button>
          </header>
          <div className="cx-panel-body">
            <div className="bg-white rounded-xl border border-ink-200 shadow-sm p-5 grid grid-cols-3 gap-4">
              <div>
                <FieldLabel>latency เฉลี่ย</FieldLabel>
                <div className="text-2xl font-extrabold text-ink-900 tabular-nums">
                  {healthHist?.avg_latency_ms != null
                    ? healthHist.avg_latency_ms
                    : "—"}
                  <span className="ml-1 text-xs font-normal text-ink-400">
                    ms
                  </span>
                </div>
              </div>
              <div>
                <FieldLabel>latency สูงสุด</FieldLabel>
                <div className="text-2xl font-extrabold text-ink-900 tabular-nums">
                  {healthHist?.max_latency_ms != null
                    ? healthHist.max_latency_ms
                    : "—"}
                  <span className="ml-1 text-xs font-normal text-ink-400">
                    ms
                  </span>
                </div>
              </div>
              <div>
                <FieldLabel>รอบที่ healthy</FieldLabel>
                <div className="text-2xl font-extrabold text-emerald-600 tabular-nums">
                  {healthHist?.healthy_ratio != null
                    ? `${Math.round(healthHist.healthy_ratio * 1000) / 10}%`
                    : "—"}
                </div>
                <div className="text-[11px] text-ink-400">
                  จาก {healthHist?.count ?? 0} รอบที่บันทึกไว้
                </div>
              </div>
            </div>

            <div className="mt-3 bg-white border border-ink-200 p-4">
              <div className="text-[10px] font-mono font-semibold text-ink-500 uppercase tracking-wider mb-2">
                Response time · min–max band
              </div>
              {healthHist && healthHist.points.length > 0 ? (
                <LatencyBandChart
                  points={healthHist.points.map((p) => ({
                    at: p.at ?? null,
                    latency_ms:
                      typeof p.latency_ms === "number" ? p.latency_ms : null,
                  }))}
                  height={200}
                  formatLabel={(at) =>
                    parseUTC(at).toLocaleTimeString("th-TH", {
                      timeZone: "Asia/Bangkok",
                      hour: "2-digit",
                      minute: "2-digit",
                      hour12: false,
                    })
                  }
                />
              ) : (
                <div className="text-sm text-ink-400 text-center py-8">
                  ยังไม่มีประวัติ — health loop บันทึกทุก 5 นาที
                </div>
              )}
            </div>
          </div>
        </section>

        {/* Pending change requests banner */}
        {pendings.length > 0 && (
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
            <div className="text-xs font-bold text-amber-900 uppercase tracking-wider mb-2">
              Pending Approval · {pendings.length} request
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

        {msg && <div className={`cx-msg ${msg.kind}`}>{msg.text}</div>}

        {/* Identity card */}
        <section className="cx-panel">
          <header>
            <div>
              <span>oauth client</span>
              <h2>OAuth Client</h2>
            </div>
          </header>
          <div className="cx-panel-body grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-5">
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

            <div className="md:col-span-2">
              <FieldLabel>Redirect URIs</FieldLabel>
              {sub.redirect_uris && sub.redirect_uris.length > 0 ? (
                <ul className="space-y-1.5">
                  {sub.redirect_uris.map((u) => (
                    <li
                      key={u}
                      className="font-mono text-[12px] text-ink-700 break-all"
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

        {/* Subsystem roles */}
        <section className="cx-panel">
          <header>
            <div>
              <span>access configuration</span>
              <h2>Roles in Subsystem</h2>
            </div>
            <button
              type="button"
              onClick={openEditModal}
              className="px-3 py-2 rounded-lg border border-ink-200 hover:bg-ink-50 text-sm font-semibold text-ink-700"
            >
              จัดการ Roles
            </button>
          </header>
          <div className="cx-panel-body">
            <p className="text-xs text-ink-500 mb-3">
              กำหนด role ที่เลือกได้ตอนเพิ่มหรือแก้ไขผู้ใช้ใน whitelist โดยการเปลี่ยนแปลงต้องผ่านการอนุมัติจากแอดมิน
            </p>
            <div className="flex flex-wrap gap-2">
              {(sub.allowed_roles?.length ? sub.allowed_roles : ["user"]).map((role) => (
                <span key={role} className="px-2.5 py-1 rounded-md bg-brand-50 border border-brand-200 text-brand-800 text-xs font-mono">
                  {role}
                </span>
              ))}
            </div>
          </div>
        </section>

        {/* Whitelist */}
        <section className="cx-panel">
          <header>
            <div>
              <span>access whitelist</span>
              <h2>Whitelist</h2>
            </div>
          </header>
          <div className="cx-panel-body">

          {whitelistError && (
            <div className="mb-3 p-3 rounded-lg bg-amber-50 border border-amber-200 text-amber-800 text-xs">
              {whitelistError}
            </div>
          )}

          {/* Add user form */}
          <form
            onSubmit={addUser}
            className="mb-3 rounded-xl border border-ink-200 bg-white shadow-sm p-4"
          >
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex-1 min-w-[220px]">
                <FieldLabel>เพิ่ม user (อีเมล)</FieldLabel>
                <input
                  type="email"
                  placeholder="user@uni.ac.th"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  required
                  className="h-10 w-full px-3 rounded-lg border border-ink-200 focus:outline-none focus:border-brand-500 text-sm"
                />
              </div>
              <div className="w-40">
                <FieldLabel>Role in sub</FieldLabel>
                <select
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value)}
                  className="h-10 w-full px-3 rounded-lg border border-ink-200 bg-white focus:outline-none focus:border-brand-500 text-sm"
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
              </div>
              <button
                type="submit"
                disabled={busyAdd}
                className="h-10 px-5 rounded-lg bg-brand-600 hover:bg-brand-700 text-white text-sm font-semibold disabled:opacity-50 transition"
              >
                {busyAdd ? "กำลังเพิ่ม…" : "+ เพิ่ม"}
              </button>
            </div>
            <div className="mt-2 text-[10px] text-ink-400">
              ระบบรับ role: {(sub.allowed_roles || ["user"]).join(", ")}
            </div>
          </form>

          {/* CSV upload */}
          <div className="mb-3 rounded-xl border border-ink-200 bg-ink-50/60 p-4 flex flex-wrap items-center gap-3">
            <div className="flex-1 min-w-[200px]">
              <div className="text-xs font-bold text-ink-700">
                อัปโหลด CSV (bulk add)
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
              className="text-xs file:mr-3 file:rounded-lg file:border-0 file:bg-ink-200 file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-ink-700 hover:file:bg-ink-300"
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
                Upload สำเร็จ — เพิ่ม {csvResult.added} คน, ข้าม{" "}
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
          </div>
        </section>

        {/* ── Active Sessions (read-only) ── */}
        <section className="cx-panel cx-active-panel">
          <header>
            <div>
              <span>active sessions · realtime</span>
              <h2>
                Active Sessions{" "}
                {active && (
                  <span className="text-sky-600 font-extrabold tabular-nums">
                    ({active.count})
                  </span>
                )}
              </h2>
            </div>
            <button onClick={loadActive} className="cx-refresh" title="Refresh">
              refresh
            </button>
          </header>
          <div className="overflow-hidden">
            {active === null ? (
              <div className="p-6 text-center text-ink-400 text-sm">
                กำลังโหลด…
              </div>
            ) : active.sessions.length === 0 ? (
              <div className="p-6 text-center text-ink-400 text-sm">
                ไม่มี session ที่ยังใช้งานได้ตอนนี้
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-ink-50">
                    <tr className="text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider">
                      <th className="px-4 py-3">ผู้ใช้</th>
                      <th className="px-4 py-3">Type</th>
                      <th className="px-4 py-3">Device</th>
                      <th className="px-4 py-3">IP / Country</th>
                      <th className="px-4 py-3">Login</th>
                      <th className="px-4 py-3">ระยะเวลา</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink-100">
                    {active.sessions.map((s) => (
                      <tr key={s.session_id} className="hover:bg-ink-50/50">
                        <td className="px-4 py-3">
                          <div className="font-semibold text-ink-900">
                            {s.full_name || s.user_email || "—"}
                          </div>
                          <div className="text-[11px] text-ink-500 font-mono">
                            {s.user_email}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <Badge
                            tone={s.user_type === "admin" ? "danger" : "brand"}
                          >
                            {(s.user_type || "—").toUpperCase()}
                          </Badge>
                        </td>
                        <td className="px-4 py-3 text-xs text-ink-700">
                          {[s.browser, s.os_name].filter(Boolean).join(" · ") ||
                            "—"}
                        </td>
                        <td className="px-4 py-3 font-mono text-[11px] text-ink-700">
                          <div>{s.ip || "—"}</div>
                          {s.geo_country && (
                            <div className="text-ink-400 uppercase">
                              {s.geo_country}
                              {s.geo_city ? ` · ${s.geo_city}` : ""}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3 font-mono text-[11px] text-ink-500">
                          {s.login_at
                            ? parseUTC(s.login_at).toLocaleString("th-TH", {
                                timeZone: "Asia/Bangkok",
                                hour: "2-digit",
                                minute: "2-digit",
                                second: "2-digit",
                                hour12: false,
                              })
                            : "—"}
                        </td>
                        <td className="px-4 py-3 text-xs tabular-nums">
                          <div className="font-semibold text-sky-700">
                            {formatDuration(s.duration_sec)}
                          </div>
                          {s.session_expires_at && (
                            <div
                              className="text-[10px] text-ink-400"
                              title="session น่าจะหมดอายุประมาณนี้ (ตาม cookie subsystem)"
                            >
                              valid ถึง ~
                              {parseUTC(s.session_expires_at).toLocaleTimeString(
                                "th-TH",
                                {
                                  timeZone: "Asia/Bangkok",
                                  hour: "2-digit",
                                  minute: "2-digit",
                                  hour12: false,
                                }
                              )}
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </section>

        {/* ── Audit Trail ── */}
        <section className="cx-panel">
          <header>
            <div>
              <span>
                audit trail · {auditTotal.toLocaleString("en-US")} รายการ
              </span>
              <h2>Audit Trail</h2>
            </div>
            {auditTotal > AUDIT_PAGE && (
              <div className="flex items-center gap-2 text-xs">
                <button
                  onClick={() =>
                    loadAudit(Math.max(0, auditOffset - AUDIT_PAGE))
                  }
                  disabled={auditOffset === 0}
                  className="px-2 py-1 rounded border border-ink-200 hover:bg-ink-50 disabled:opacity-40"
                >
                  ← ก่อนหน้า
                </button>
                <span className="text-ink-500 font-mono">
                  {auditOffset + 1}–
                  {Math.min(auditOffset + AUDIT_PAGE, auditTotal)} / {auditTotal}
                </span>
                <button
                  onClick={() => loadAudit(auditOffset + AUDIT_PAGE)}
                  disabled={auditOffset + AUDIT_PAGE >= auditTotal}
                  className="px-2 py-1 rounded border border-ink-200 hover:bg-ink-50 disabled:opacity-40"
                >
                  ถัดไป →
                </button>
              </div>
            )}
          </header>
          <div className="overflow-hidden">
            {audit === null ? (
              <div className="p-6 text-center text-ink-400 text-sm">
                กำลังโหลด…
              </div>
            ) : audit.length === 0 ? (
              <div className="p-6 text-center text-ink-400 text-sm">
                ไม่มี activity
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-ink-50">
                    <tr className="text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider">
                      <th className="px-4 py-3">เวลา</th>
                      <th className="px-4 py-3">ผู้กระทำ</th>
                      <th className="px-4 py-3">การกระทำ</th>
                      <th className="px-4 py-3">IP</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink-100">
                    {audit.map((a) => (
                      <tr key={a.id} className="hover:bg-ink-50/50">
                        <td className="px-4 py-3 font-mono text-[11px] whitespace-nowrap">
                          {a.created_at
                            ? parseUTC(a.created_at).toLocaleString("th-TH", {
                                timeZone: "Asia/Bangkok",
                                year: "numeric",
                                month: "2-digit",
                                day: "2-digit",
                                hour: "2-digit",
                                minute: "2-digit",
                                second: "2-digit",
                                hour12: false,
                              })
                            : "—"}
                        </td>
                        <td className="px-4 py-3">
                          {a.actor_email ? (
                            <span className="font-mono text-xs">
                              {a.actor_email}
                            </span>
                          ) : (
                            <span className="text-ink-400 italic text-xs">
                              system
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <Badge tone="default">{a.action}</Badge>
                        </td>
                        <td className="px-4 py-3 font-mono text-xs">
                          {a.ip || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </section>

        <div className="pt-4 text-center text-[11px] text-ink-400 font-mono">
          subsystem_id: {sub.id}
        </div>
      </main>
      </div>

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
                className="text-ink-400 hover:text-ink-700 text-sm"
              >
                ปิด
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3">
                <strong>การแก้ Scope, Allowed Roles, Redirect URIs</strong>{" "}
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

function KpiCard({
  label,
  value,
  tone = "default",
  sub,
}: {
  label: string;
  value: string;
  tone?: "default" | "brand" | "good" | "danger";
  sub?: string;
}) {
  const toneClass =
    tone === "good"
      ? "signal"
      : tone === "danger"
      ? "danger"
      : tone === "brand"
      ? "info"
      : "";
  return (
    <article className={`cx-kpi ${toneClass}`}>
      <span>{label}</span>
      <strong className="mono">{value}</strong>
      {sub && <small className="mono">{sub}</small>}
    </article>
  );
}
