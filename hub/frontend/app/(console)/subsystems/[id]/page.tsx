"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge } from "@/components/Badge";
import { SlidePanel } from "@/components/SlidePanel";
import { clientFetch } from "@/lib/api";
import { mutateWithStepup, runWithStepup } from "@/lib/passkey";
import { AccessPolicyCard } from "./_components/AccessPolicyCard";

/** ดึงข้อความ error ที่อ่านได้ — รองรับ detail เป็น object (no_passkey) + ยกเลิก Passkey */
function errText(e: unknown, fallback: string): string {
  if (e instanceof DOMException && e.name === "NotAllowedError")
    return "ยกเลิกการยืนยัน Passkey — ลองอีกครั้ง";
  const d = (e as { detail?: unknown })?.detail;
  if (typeof d === "string") return d;
  if (d && typeof d === "object") {
    const code = (d as { code?: string }).code;
    if (code === "no_passkey")
      return "ต้องมี Passkey เพื่อยืนยันการกระทำนี้ — ตั้งค่าที่หน้าบัญชี/ความปลอดภัย หรือใช้ Account Recovery";
  }
  return fallback;
}

// ── Types ──────────────────────────────────────────────────
type HealthStatus = {
  status: "online" | "degraded" | "down" | "unknown";
  latency_ms?: number;
  checked_at?: string;
  url?: string;
  error?: string;
};

type Subsystem = {
  id: string;
  name: string;
  description?: string;
  client_id: string;
  status: string;
  // scope ใน DB เป็น text[] → JSON เป็น array (ไม่ใช่ string!)
  scope?: string[] | string | null;
  allowed_roles?: string[];
  access_policy?: string;
  access_policy_config?: {
    roles?: string[];
    faculty?: string[];
    major?: string[];
  } | null;
  api_key_prefix?: string | null;
  access_revoke_webhook_url?: string | null;
  whitelist_count: number;
  owner_email?: string;
  redirect_uris?: string[];
  created_at?: string;
  approved_at?: string;
  previous_secret_expires_at?: string | null;
  health?: HealthStatus | null;
};

const HEALTH_TONE: Record<
  string,
  { label: string; bg: string; color: string; emoji: string }
> = {
  online: {
    label: "ONLINE",
    bg: "bg-emerald-100 border-emerald-300",
    color: "text-emerald-800",
    emoji: "🟢",
  },
  degraded: {
    label: "DEGRADED",
    bg: "bg-amber-100 border-amber-300",
    color: "text-amber-800",
    emoji: "🟡",
  },
  down: {
    label: "DOWN",
    bg: "bg-rose-100 border-rose-300",
    color: "text-rose-800",
    emoji: "🔴",
  },
  unknown: {
    label: "UNKNOWN",
    bg: "bg-ink-100 border-ink-200",
    color: "text-ink-600",
    emoji: "⚪",
  },
};

type RotateSecretResponse = {
  client_id: string;
  secret_delivery: "email" | "url";  // pragma: allowlist secret
  secret_sent_to?: string | null;
  secret_retrieval_url?: string | null;
  grace_hours: number;
  previous_expires_at: string;
  warning?: string | null;
  message: string;
};

type WhitelistEntry = {
  user_id: string;
  email: string;
  full_name?: string;
  user_type?: string;
  user_status?: string;
  role_in_sub?: string;
  granted_at?: string;
  revoked_at?: string | null;
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

type AuditItem = {
  id: string;
  actor_id: string | null;
  actor_email: string | null;
  actor_user_type: string | null;
  actor_is_hub_admin: boolean;
  action: string;
  target_type: string;
  target_id: string | null;
  ip: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string | null;
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
  duration_sec: number;
};

type ActiveSessionsResponse = {
  subsystem: { id: string; name: string };
  count: number;
  sessions: ActiveSession[];
};

const DEVICE_ICON: Record<string, string> = {
  desktop: "💻",
  mobile: "📱",
  tablet: "📟",
  bot: "🤖",
  unknown: "❓",
};

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
  const [selectedAudit, setSelectedAudit] = useState<AuditItem | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [newEmail, setNewEmail] = useState("");
  const [newRole, setNewRole] = useState("user");
  // CSV bulk upload
  const [csvResult, setCsvResult] = useState<CsvUploadResponse | null>(null);
  const [csvUploading, setCsvUploading] = useState(false);
  const csvInputRef = useRef<HTMLInputElement>(null);
  const [busyAdd, setBusyAdd] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(
    null
  );
  // inline step-up — true ระหว่างทำ Passkey ceremony (critical action)
  const [verifying, setVerifying] = useState(false);

  // Active sessions
  const [active, setActive] = useState<ActiveSessionsResponse | null>(null);
  // Stats
  const [stats, setStats] = useState<StatsResponse | null>(null);
  // Inline role editing
  const [editingRoleFor, setEditingRoleFor] = useState<string | null>(null);
  const [editingRoleValue, setEditingRoleValue] = useState("");
  // Edit subsystem modal
  const [editOpen, setEditOpen] = useState(false);
  const [editDesc, setEditDesc] = useState("");
  const [editRedirects, setEditRedirects] = useState("");
  const [editScope, setEditScope] = useState<Set<string>>(new Set());
  const [editAllowedRoles, setEditAllowedRoles] = useState("");
  const [editWebhookUrl, setEditWebhookUrl] = useState("");
  const [editBusy, setEditBusy] = useState(false);

  // ALLOWED_SCOPES — ต้องตรงกับ backend developer.py
  const SCOPE_OPTIONS: Array<{ key: string; label: string; desc: string }> = [
    { key: "email", label: "Email", desc: "อีเมลของผู้ใช้" },
    { key: "name", label: "Full Name", desc: "ชื่อ-นามสกุล" },
    { key: "student_id", label: "Student ID", desc: "รหัสนักศึกษา (เฉพาะนักศึกษา)" },
    { key: "employee_id", label: "Employee ID", desc: "รหัสบุคลากร" },
    { key: "faculty", label: "Faculty", desc: "คณะ" },
    { key: "major", label: "Major", desc: "สาขาวิชา" },
    { key: "year", label: "Year", desc: "ชั้นปี (เฉพาะนักศึกษา)" },
    { key: "position", label: "Position", desc: "ตำแหน่ง (เฉพาะบุคลากร)" },
    { key: "phone", label: "Phone", desc: "เบอร์โทรศัพท์" },
    { key: "address", label: "Address", desc: "ที่อยู่" },
  ];

  function toggleEditScope(key: string) {
    setEditScope((s) => {
      const next = new Set(s);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }
  // Control busy (suspend/resume)
  const [ctlBusy, setCtlBusy] = useState(false);
  // Revoke session busy (per session_id)
  const [revokingId, setRevokingId] = useState<string | null>(null);
  // Revoke menu open (per session_id) + anchor position
  const [revokeMenuFor, setRevokeMenuFor] = useState<string | null>(null);
  const [revokeMenuPos, setRevokeMenuPos] = useState<{
    top: number;
    right: number;
  } | null>(null);

  function openRevokeMenu(sessionId: string, e: React.MouseEvent<HTMLButtonElement>) {
    if (revokeMenuFor === sessionId) {
      setRevokeMenuFor(null);
      return;
    }
    const rect = e.currentTarget.getBoundingClientRect();
    setRevokeMenuPos({
      top: rect.bottom + 4,
      right: window.innerWidth - rect.right,
    });
    setRevokeMenuFor(sessionId);
  }
  // Rotate secret
  const [rotateBusy, setRotateBusy] = useState(false);
  const [rotateResult, setRotateResult] =
    useState<RotateSecretResponse | null>(null);
  // Transfer ownership
  const [transferOpen, setTransferOpen] = useState(false);
  const [transferEmail, setTransferEmail] = useState("");
  const [transferBusy, setTransferBusy] = useState(false);
  // Bulk role update
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkRole, setBulkRole] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);

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
        // หลัง Phase 1 admin override: backend ให้ admin ดู whitelist ของทุก subsystem
        // ถ้ายัง error → แสดง detail ตรง ๆ (น่าจะเป็น 500 / network)
        const detail = (e as { detail?: string }).detail || "";
        setWhitelistError(detail || "โหลด whitelist ไม่สำเร็จ");
      });
  }, [id]);

  const [auditOffset, setAuditOffset] = useState(0);
  const [auditTotal, setAuditTotal] = useState(0);
  const AUDIT_PAGE = 50;
  const loadAudit = useCallback(
    (offset: number = 0) => {
      clientFetch<{ items: AuditItem[]; total: number }>(
        `/admin/subsystems/${id}/audit?skip=${offset}&limit=${AUDIT_PAGE}`
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

  const loadActive = useCallback(() => {
    clientFetch<ActiveSessionsResponse>(
      `/admin/subsystems/${id}/active-sessions`
    )
      .then(setActive)
      .catch(() => setActive(null));
  }, [id]);

  const loadStats = useCallback(() => {
    clientFetch<StatsResponse>(`/admin/subsystems/${id}/stats?days=7`)
      .then(setStats)
      .catch(() => setStats(null));
  }, [id]);

  useEffect(() => {
    loadSubsystem();
    loadWhitelist();
    loadAudit();
    loadActive();
    loadStats();
  }, [loadSubsystem, loadWhitelist, loadAudit, loadActive, loadStats]);

  // Sync default role-to-add กับ allowed_roles ของ subsystem
  useEffect(() => {
    if (sub?.allowed_roles?.length) {
      const allowed = sub.allowed_roles;
      if (!allowed.includes(newRole)) {
        setNewRole(allowed[0]);
      }
    }
    // newRole ตั้งใจไม่ใส่ใน dep — เพื่อให้ effect รันเฉพาะตอน subsystem โหลด
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sub]);

  // Auto-refresh active sessions ทุก 10 วินาที (เด้งทันทีหลัง config/whitelist/role change)
  useEffect(() => {
    const t = setInterval(loadActive, 10_000);
    return () => clearInterval(t);
  }, [loadActive]);

  async function uploadCsv(file: File) {
    setCsvUploading(true);
    setCsvResult(null);
    setMsg(null);
    try {
      const form = new FormData();
      form.append("file", file);
      // FormData → ยิง /api/proxy ตรง (clientFetch บังคับ JSON header)
      // backend admin override → admin อัปโหลด whitelist ของ subsystem ใดก็ได้
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
      loadAudit();
      loadActive();
    } catch (e) {
      setMsg({ kind: "err", text: errText(e, "Upload CSV ไม่สำเร็จ") });
    } finally {
      setCsvUploading(false);
      if (csvInputRef.current) csvInputRef.current.value = "";
    }
  }

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
          // backend WhitelistAddUser ใช้ field 'role' (ไม่ใช่ role_in_sub)
          body: JSON.stringify({ email: newEmail.trim(), role: newRole }),
        },
        setVerifying
      );
      setMsg({ kind: "ok", text: `เพิ่ม ${newEmail} เข้า whitelist แล้ว` });
      setNewEmail("");
      loadWhitelist();
      loadAudit();
      loadActive();
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
      loadAudit();
      loadActive();
    } catch (e) {
      setMsg({ kind: "err", text: errText(e, "ลบไม่สำเร็จ") });
    }
  }

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
      loadAudit();
      loadActive();
    } catch (e) {
      setMsg({ kind: "err", text: errText(e, "เปลี่ยน role ไม่สำเร็จ") });
    }
  }

  async function suspendSubsystem() {
    if (!confirm(`ระงับใช้งาน "${sub?.name}"? login ใหม่จะถูกปฏิเสธ`)) return;
    setCtlBusy(true);
    setMsg(null);
    try {
      await mutateWithStepup(
        `/admin/subsystems/${id}/suspend`,
        { method: "POST" },
        setVerifying
      );
      setMsg({ kind: "ok", text: "ระงับใช้งานแล้ว" });
      loadSubsystem();
      loadAudit();
      loadActive();
    } catch (e) {
      setMsg({ kind: "err", text: errText(e, "ระงับไม่สำเร็จ") });
    } finally {
      setCtlBusy(false);
    }
  }

  function toggleSelect(uid: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(uid)) next.delete(uid);
      else next.add(uid);
      return next;
    });
  }
  function selectAll() {
    if (!whitelist) return;
    setSelectedIds(new Set(whitelist.map((u) => u.user_id)));
  }
  function clearSelection() {
    setSelectedIds(new Set());
  }

  async function applyBulkRole() {
    if (selectedIds.size === 0 || !bulkRole.trim()) return;
    if (
      !confirm(
        `เปลี่ยน role ของ ${selectedIds.size} คน เป็น "${bulkRole}" ?`
      )
    )
      return;
    setBulkBusy(true);
    setMsg(null);
    try {
      const updates = Array.from(selectedIds).map((uid) => ({
        user_id: uid,
        role_in_sub: bulkRole,
      }));
      const r = await mutateWithStepup<{
        changed: number;
        skipped: number;
        message: string;
      }>(
        `/developer/subsystems/${id}/whitelist/bulk-update`,
        {
          method: "POST",
          body: JSON.stringify({ updates }),
        },
        setVerifying
      );
      setMsg({ kind: "ok", text: r.message });
      clearSelection();
      loadWhitelist();
      loadAudit();
      loadActive();
    } catch (e) {
      setMsg({ kind: "err", text: errText(e, "bulk update ไม่สำเร็จ") });
    } finally {
      setBulkBusy(false);
    }
  }

  async function submitTransfer() {
    if (!transferEmail.trim()) return;
    setTransferBusy(true);
    setMsg(null);
    try {
      const r = await mutateWithStepup<{ message: string }>(
        `/developer/subsystems/${id}/transfer-owner`,
        {
          method: "POST",
          body: JSON.stringify({ new_owner_email: transferEmail.trim() }),
        },
        setVerifying
      );
      setMsg({ kind: "ok", text: r.message });
      setTransferOpen(false);
      setTransferEmail("");
      loadSubsystem();
      loadAudit();
    } catch (e) {
      setMsg({ kind: "err", text: errText(e, "โอน ownership ไม่สำเร็จ") });
    } finally {
      setTransferBusy(false);
    }
  }

  async function rotateSecret() {
    if (
      !confirm(
        `หมุน client_secret ของ "${sub?.name}"? secret ใหม่จะใช้แทนตัวเดิมทันที — ` +
          `แต่ตัวเดิมยังใช้ได้ 24 ชม. เพื่อให้คุณ deploy secret ใหม่ใส่ .env ของ subsystem`
      )
    )
      return;
    setRotateBusy(true);
    setMsg(null);
    try {
      const r = await mutateWithStepup<RotateSecretResponse>(
        `/developer/subsystems/${id}/rotate-secret`,
        { method: "POST" },
        setVerifying
      );
      setRotateResult(r);
      setMsg({ kind: "ok", text: r.message });
      loadSubsystem();
      loadAudit();
    } catch (e) {
      setMsg({ kind: "err", text: errText(e, "rotate secret ไม่สำเร็จ") });
    } finally {
      setRotateBusy(false);
    }
  }

  async function revokeSession(
    sessionId: string,
    email: string | null,
    level: "notify" | "challenge" | "ban"
  ) {
    const labels: Record<string, string> = {
      notify: "เตะออก + แจ้ง email (login ใหม่ได้ทันที)",
      challenge: "เตะออก + ต้องยืนยันตัวตนทาง email ก่อน login ใหม่",
      ban: "เตะออก + ลบจาก whitelist (login ใหม่ไม่ได้)",
    };
    if (
      !confirm(
        `Revoke ${email || "session นี้"}\n\n` +
          `ระดับ: ${level.toUpperCase()}\n` +
          `${labels[level]}\n\n` +
          `ยืนยัน?`
      )
    )
      return;
    setRevokingId(sessionId);
    setRevokeMenuFor(null);
    setMsg(null);
    try {
      const r = await mutateWithStepup<{ message: string }>(
        `/admin/subsystems/${id}/sessions/${sessionId}/revoke?level=${level}`,
        { method: "POST" },
        setVerifying
      );
      setMsg({ kind: "ok", text: r.message });
      loadActive();
      loadAudit();
      loadWhitelist();
    } catch (e) {
      setMsg({ kind: "err", text: errText(e, "revoke ไม่สำเร็จ") });
    } finally {
      setRevokingId(null);
    }
  }

  async function resumeSubsystem() {
    setCtlBusy(true);
    setMsg(null);
    try {
      await mutateWithStepup(
        `/admin/subsystems/${id}/resume`,
        { method: "POST" },
        setVerifying
      );
      setMsg({ kind: "ok", text: "เปิดใช้งานอีกครั้งแล้ว" });
      loadSubsystem();
      loadAudit();
    } catch (e) {
      setMsg({ kind: "err", text: errText(e, "เปิดใช้งานไม่สำเร็จ") });
    } finally {
      setCtlBusy(false);
    }
  }

  function openEditModal() {
    if (!sub) return;
    setEditDesc(sub.description || "");
    setEditRedirects((sub.redirect_uris || []).join("\n"));
    setEditScope(new Set(scopeList(sub.scope)));
    setEditAllowedRoles((sub.allowed_roles || []).join(", "));
    setEditWebhookUrl(sub.access_revoke_webhook_url || "");
    setEditOpen(true);
  }

  async function saveEditSubsystem() {
    setEditBusy(true);
    setMsg(null);
    const body: Record<string, unknown> = {};
    if (editDesc !== (sub?.description || "")) body.description = editDesc;

    const redirects = editRedirects
      .split(/\n+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (
      JSON.stringify(redirects) !== JSON.stringify(sub?.redirect_uris || [])
    ) {
      body.redirect_uris = redirects;
    }

    const scopeArr = Array.from(editScope);
    const currentScope = scopeList(sub?.scope).slice().sort();
    if (JSON.stringify(scopeArr.slice().sort()) !== JSON.stringify(currentScope)) {
      body.scope = scopeArr;
    }

    const rolesArr = editAllowedRoles
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    const currentRoles = (sub?.allowed_roles || []).slice();
    if (JSON.stringify(rolesArr) !== JSON.stringify(currentRoles)) {
      body.allowed_roles = rolesArr;
    }

    const webhook = editWebhookUrl.trim();
    if (webhook !== (sub?.access_revoke_webhook_url || "")) {
      body.access_revoke_webhook_url = webhook;
    }

    if (Object.keys(body).length === 0) {
      setMsg({ kind: "ok", text: "ไม่มีการเปลี่ยนแปลง" });
      setEditOpen(false);
      setEditBusy(false);
      return;
    }

    try {
      const r = await mutateWithStepup<{ result: string; needs_reapproval?: boolean }>(
        `/developer/subsystems/${id}`,
        { method: "PATCH", body: JSON.stringify(body) },
        setVerifying
      );
      setMsg({
        kind: r.needs_reapproval ? "err" : "ok",
        text: r.result,
      });
      setEditOpen(false);
      loadSubsystem();
      loadAudit();
      loadActive();
    } catch (e) {
      setMsg({ kind: "err", text: errText(e, "แก้ไขไม่สำเร็จ") });
    } finally {
      setEditBusy(false);
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
      key: "_select",
      header: "",
      width: "40px",
      render: (u) => (
        <input
          type="checkbox"
          checked={selectedIds.has(u.user_id)}
          onChange={() => toggleSelect(u.user_id)}
          onClick={(e) => e.stopPropagation()}
          className="accent-brand-600"
          aria-label={`เลือก ${u.email}`}
        />
      ),
    },
    {
      key: "full_name",
      header: "ผู้ใช้",
      render: (u) => {
        const isDeleted = u.user_status === "deleted";
        return (
          <div className={isDeleted ? "opacity-60" : ""}>
            <div className="flex items-center gap-2 flex-wrap">
              <span
                className={
                  "font-semibold " +
                  (isDeleted ? "text-ink-500 line-through" : "text-ink-900")
                }
              >
                {u.full_name || u.email}
              </span>
              {isDeleted && (
                <span
                  className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-rose-100 text-rose-700 border border-rose-200"
                  title="user ถูกลบที่ Hub — sessions ถูกตัด + whitelist ถูก revoke"
                >
                  🚫 deleted
                </span>
              )}
            </div>
            <div className="text-[11px] text-ink-500 font-mono">{u.email}</div>
          </div>
        );
      },
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

  // Action → friendly Thai label
  const ACTION_LABELS: Record<string, string> = {
    token_issued: "ออก JWT token",
    oauth_authorized: "อนุญาต OAuth",
    oauth_login_failed_not_in_whitelist: "บล็อก login (ไม่อยู่ใน whitelist)",
    oauth_preflight_subsystem_down: "Preflight ล้มเหลว (subsystem ลง)",
    subsystem_registered: "ลงทะเบียน subsystem",
    subsystem_approved: "อนุมัติ subsystem",
    subsystem_rejected: "ปฏิเสธ subsystem",
    subsystem_suspended: "ระงับใช้งาน subsystem",
    subsystem_resumed: "เปิดใช้งาน subsystem อีกครั้ง",
    subsystem_updated: "แก้ไข subsystem",
    subsystem_logout: "Logout จาก subsystem",
    subsystem_owner_transferred: "โอนกรรมสิทธิ์ subsystem",
    whitelist_user_added: "เพิ่ม user เข้า whitelist",
    whitelist_user_removed: "ลบ user ออกจาก whitelist",
    whitelist_user_restored: "คืน user เข้า whitelist",
    whitelist_uploaded: "อัปโหลด whitelist (bulk)",
    whitelist_role_changed: "เปลี่ยน role ของ user",
    whitelist_role_change_requested: "ขอเปลี่ยน role (รออนุมัติ)",
    whitelist_bulk_role_update: "เปลี่ยน role แบบ bulk",
    whitelist_bulk_role_update_requested: "ขอเปลี่ยน role แบบ bulk (รออนุมัติ)",
    client_secret_rotated: "หมุน client_secret", // pragma: allowlist secret
    rotate_secret_requested: "ขอหมุน client_secret (รออนุมัติ)", // pragma: allowlist secret
    secret_retrieved: "ดู client_secret", // pragma: allowlist secret
    change_request_created: "สร้างคำขอ approval",
    change_request_approved: "อนุมัติคำขอ",
    change_request_rejected: "ปฏิเสธคำขอ",
    change_request_admin_auto_approved: "Admin auto-approve",
    user_force_revoked_notify: "🔔 บังคับ logout (แจ้ง)",
    user_force_revoked_challenge: "🛡️ บังคับ logout (ต้อง confirm ก่อน login)",
    user_force_revoked_ban: "🚫 บังคับ logout + แบนถาวร",
  };
  const labelFor = (action: string) => ACTION_LABELS[action] || action;

  // build รายละเอียด from action + metadata
  const detailFor = (a: AuditItem): string => {
    const m = (a.metadata || {}) as Record<string, unknown>;
    const userEmail = (m.user_email as string | undefined) || "";
    const userName = (m.user_full_name as string | undefined) || "";
    const wd = m.webhook_delivered as boolean | null | undefined;
    const level = (m.level as string | undefined) || "";
    const parts: string[] = [];
    if (userEmail || userName) {
      parts.push(`เป้าหมาย: ${userName || ""} ${userEmail ? `<${userEmail}>` : ""}`.trim());
    }
    if (a.action.startsWith("user_force_revoked_")) {
      if (level) parts.push(`ระดับ: ${level}`);
      if (wd === true) parts.push("✓ webhook ส่งถึง subsystem");
      else if (wd === false) parts.push("✗ webhook ส่งไม่ถึง");
    }
    // whitelist_role_changed / bulk metadata
    const removed = m.removed_user_id as string | undefined;
    if (a.action === "whitelist_user_removed" && removed) {
      parts.push(`user_id: ${removed.slice(0, 8)}…`);
    }
    const email = m.email as string | undefined;
    const role = m.role as string | undefined;
    if ((a.action === "whitelist_user_added" || a.action === "whitelist_user_restored") && email) {
      parts.push(`${email}${role ? ` (${role})` : ""}`);
    }
    return parts.join(" · ") || "—";
  };

  // Role label + tone — hub_admin override > user_type
  const roleInfoFor = (
    a: AuditItem
  ): { label: string; tone: "brand" | "good" | "warn" | "danger" | "default" } => {
    if (a.actor_is_hub_admin) return { label: "Hub Admin", tone: "danger" };
    const t = a.actor_user_type;
    if (!t) return { label: "system", tone: "default" };
    const map: Record<string, { label: string; tone: "brand" | "good" | "warn" | "danger" | "default" }> = {
      admin: { label: "admin", tone: "danger" },
      staff: { label: "staff", tone: "warn" },
      teacher: { label: "teacher", tone: "brand" },
      student: { label: "student", tone: "default" },
    };
    return map[t] || { label: t, tone: "default" };
  };

  const actionTone = (
    action: string
  ): "brand" | "good" | "warn" | "danger" | "default" => {
    if (action.includes("approved") || action.includes("success")) return "good";
    if (
      action.includes("rejected") ||
      action.includes("failed") ||
      action.includes("blocked")
    )
      return "danger";
    if (action.includes("login") || action.includes("token")) return "brand";
    if (action.includes("revoked") || action.includes("suspended")) return "warn";
    return "default";
  };

  const auditCols: Column<AuditItem & Record<string, unknown>>[] = [
    {
      key: "created_at",
      header: "เวลา",
      render: (a) => (
        <span className="font-mono text-xs whitespace-nowrap">
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
        </span>
      ),
    },
    {
      key: "actor_email",
      header: "ผู้กระทำ",
      render: (a) =>
        a.actor_email ? (
          <span className="font-mono text-xs">{a.actor_email}</span>
        ) : (
          <span className="text-ink-400 italic text-xs">system</span>
        ),
    },
    {
      key: "actor_role",
      header: "Role",
      width: "110px",
      render: (a) => {
        const r = roleInfoFor(a);
        return <Badge tone={r.tone}>{r.label}</Badge>;
      },
    },
    {
      key: "action",
      header: "การกระทำ",
      render: (a) => <Badge tone={actionTone(a.action)}>{a.action}</Badge>,
    },
    {
      key: "ip",
      header: "IP",
      render: (a) => (
        <span className="font-mono text-xs">{a.ip || "—"}</span>
      ),
    },
    {
      key: "detail",
      header: "รายละเอียด",
      align: "right",
      width: "150px",
      render: (a) => (
        <button
          type="button"
          onClick={() => setSelectedAudit(a)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-brand-200 bg-brand-50 hover:bg-brand-100 hover:border-brand-300 text-brand-700 text-xs font-semibold transition shadow-sm hover:shadow"
          title="คลิกเพื่อดูรายละเอียดทั้งหมด"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            className="w-3.5 h-3.5"
            aria-hidden="true"
          >
            <path d="M10 12.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5z" />
            <path
              fillRule="evenodd"
              d="M.664 10.59a1.651 1.651 0 010-1.186A10.004 10.004 0 0110 3c4.257 0 7.893 2.66 9.336 6.41.147.381.146.804 0 1.186A10.004 10.004 0 0110 17c-4.257 0-7.893-2.66-9.336-6.41zM14 10a4 4 0 11-8 0 4 4 0 018 0z"
              clipRule="evenodd"
            />
          </svg>
          ดูรายละเอียด
        </button>
      ),
    },
  ];

  return (
    <>
      {verifying && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-2xl px-6 py-5 shadow-xl flex items-center gap-3 text-sm text-ink-700">
            <span className="animate-pulse text-lg">🔐</span>
            กำลังยืนยันด้วย Passkey… ทำตามที่อุปกรณ์แจ้ง
          </div>
        </div>
      )}
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
            <div className="flex items-center gap-2">
              <Badge tone={STATUS_TONE[sub.status] || "default"}>
                ● {sub.status.toUpperCase()}
              </Badge>
              {sub.health && (
                <span
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold border ${
                    HEALTH_TONE[sub.health.status]?.bg
                  } ${HEALTH_TONE[sub.health.status]?.color}`}
                  title={
                    sub.health.error ||
                    `latency ${sub.health.latency_ms ?? "?"}ms · checked ${
                      sub.health.checked_at?.slice(11, 16) || "?"
                    } UTC`
                  }
                >
                  {HEALTH_TONE[sub.health.status]?.emoji}{" "}
                  {HEALTH_TONE[sub.health.status]?.label}
                  {sub.health.latency_ms != null && (
                    <span className="font-mono opacity-70">
                      · {sub.health.latency_ms}ms
                    </span>
                  )}
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-2 items-center justify-end">
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
                title="หมุน client_secret ใหม่ (เก่ายังใช้ได้ 24 ชม.)"
              >
                {rotateBusy ? "…" : "🔑 Rotate Secret"}
              </button>
              <button
                onClick={() => setTransferOpen(true)}
                className="px-3 py-1.5 rounded-lg border border-ink-200 hover:bg-ink-50 text-xs font-semibold text-ink-700 transition"
                title="โอน ownership ให้ developer อีกคน"
              >
                ↦ โอนเจ้าของ
              </button>
              {sub.status === "active" && (
                <button
                  onClick={suspendSubsystem}
                  disabled={ctlBusy}
                  className="px-3 py-1.5 rounded-lg bg-rose-50 hover:bg-rose-100 border border-rose-200 text-xs font-semibold text-rose-700 disabled:opacity-50 transition"
                >
                  {ctlBusy ? "…" : "⏸ ระงับ"}
                </button>
              )}
              {sub.status === "suspended" && (
                <button
                  onClick={resumeSubsystem}
                  disabled={ctlBusy}
                  className="px-3 py-1.5 rounded-lg bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 text-xs font-semibold text-emerald-700 disabled:opacity-50 transition"
                >
                  {ctlBusy ? "…" : "▶ เปิดใช้งาน"}
                </button>
              )}
            </div>
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

        {/* Grace period banner */}
        {sub.previous_secret_expires_at &&
          parseUTC(sub.previous_secret_expires_at) > new Date() && (
            <div className="p-3 rounded-lg bg-amber-50 border border-amber-200 text-amber-800 text-sm">
              🔑 secret เก่ายังใช้ได้ — หมดอายุ{" "}
              <span className="font-mono font-semibold">
                {parseUTC(sub.previous_secret_expires_at).toLocaleString(
                  "th-TH",
                  {
                    timeZone: "Asia/Bangkok",
                    dateStyle: "short",
                    timeStyle: "short",
                  }
                )}
              </span>{" "}
              · deploy secret ใหม่ใส่ <code>.env</code> ของ subsystem ก่อนเวลานี้
            </div>
          )}

        {/* ── Section 0: KPI 7 วันล่าสุด ─────────────────── */}
        {stats && (
          <section>
            <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
              ภาพรวม · 7 วันล่าสุด
            </h3>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <KpiCard
                label="Login total"
                value={stats.total_logins.toLocaleString("en-US")}
                tone="brand"
              />
              <KpiCard
                label="Unique users"
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
                value={(
                  (stats.decision_breakdown.block || 0) +
                  (stats.decision_breakdown.would_block || 0)
                ).toLocaleString("en-US")}
                tone="danger"
              />
            </div>
            {/* Mini daily bar chart */}
            {stats.daily.length > 0 && (() => {
              const max = Math.max(...stats.daily.map((x) => x.count), 1);
              const BAR_AREA_PX = 80;
              return (
                <div className="mt-4 bg-white rounded-xl border border-ink-200 p-4">
                  <div className="text-[10px] font-bold text-ink-500 uppercase tracking-wider mb-2">
                    Login ต่อวัน · max={max}
                  </div>
                  <div className="flex items-end gap-2" style={{ height: `${BAR_AREA_PX + 20}px` }}>
                    {stats.daily.map((d) => {
                      const heightPx =
                        d.count > 0
                          ? Math.max(4, (d.count / max) * BAR_AREA_PX)
                          : 0;
                      return (
                        <div
                          key={d.date}
                          className="flex-1 flex flex-col items-center gap-1 justify-end"
                          title={`${d.date}: ${d.count} logins`}
                        >
                          <div className="text-[10px] text-ink-700 font-mono">
                            {d.count > 0 ? d.count : ""}
                          </div>
                          <div
                            className="w-full bg-brand-500 rounded-sm hover:bg-brand-600 transition"
                            style={{ height: `${heightPx}px` }}
                          />
                          <div className="text-[9px] text-ink-400 font-mono">
                            {d.date.slice(5)}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })()}
          </section>
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

        {/* ── Section 1.5: Active Users ──────────────────── */}
        <section>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider">
              <span className="inline-flex items-center gap-2">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                </span>
                ผู้ใช้กำลัง active{" "}
                {active && (
                  <span className="text-emerald-600 font-extrabold tabular-nums">
                    ({active.count})
                  </span>
                )}
              </span>
            </h3>
            <button
              onClick={loadActive}
              className="text-[11px] text-ink-500 hover:text-brand-600 underline"
              title="Refresh"
            >
              ⟳ refresh (auto 30s)
            </button>
          </div>
          <div className="bg-white rounded-xl border border-ink-200 shadow-sm overflow-hidden">
            {active === null ? (
              <div className="p-6 text-center text-ink-400 text-sm">
                กำลังโหลด…
              </div>
            ) : active.sessions.length === 0 ? (
              <div className="p-6 text-center text-ink-400 text-sm">
                ไม่มี user กำลังใช้งานตอนนี้
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
                      <th className="px-4 py-3 text-right">—</th>
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
                          <span className="text-base mr-1">
                            {DEVICE_ICON[s.device_type || "unknown"] || "❓"}
                          </span>
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
                        <td className="px-4 py-3 text-xs font-semibold text-emerald-700 tabular-nums">
                          {formatDuration(s.duration_sec)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            onClick={(e) => openRevokeMenu(s.session_id, e)}
                            disabled={revokingId === s.session_id}
                            className="px-2 py-1 rounded bg-rose-50 hover:bg-rose-100 border border-rose-200 text-rose-700 text-[11px] font-semibold disabled:opacity-50 transition"
                            title="เลือกระดับ revoke"
                          >
                            {revokingId === s.session_id
                              ? "…"
                              : "⛔ Revoke ▾"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </section>

        {/* ── Access Policy ───────────────────────── */}
        <AccessPolicyCard
          subId={id}
          policy={sub.access_policy || "explicit"}
          config={sub.access_policy_config}
          apiKeyPrefix={sub.api_key_prefix}
          onReload={() => {
            loadSubsystem();
            loadWhitelist();
            loadActive();
          }}
        />

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
                ระบบยอมรับ: {(sub.allowed_roles || ["user"]).join(", ")}
              </div>
            </div>
            <button
              type="submit"
              disabled={busyAdd}
              className="px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-700 text-white text-sm font-semibold disabled:opacity-50 transition"
            >
              {busyAdd ? "กำลังเพิ่ม…" : "+ เพิ่มเข้า whitelist"}
            </button>
          </form>

          {/* CSV bulk upload */}
          <div className="mb-3 bg-white rounded-xl border border-dashed border-ink-300 p-4 flex flex-wrap items-center gap-3">
            <div className="flex-1 min-w-[200px]">
              <div className="text-xs font-bold text-ink-700">
                📄 อัปโหลด CSV
              </div>
              <div className="text-[11px] text-ink-500 mt-0.5">
                CSV header: <code className="font-mono">email,role,note</code> —
                ระบบ skip คนที่ไม่อยู่ใน Hub หรือ role ไม่ตรง allowed_roles
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
                  <summary className="cursor-pointer font-medium">
                    ดูรายการที่ข้าม ({csvResult.skipped_details.length})
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

          {/* Bulk action toolbar — แสดงเมื่อเลือกแล้ว 1+ */}
          {selectedIds.size > 0 && (
            <div className="mb-2 p-3 rounded-lg bg-brand-50 border border-brand-200 flex flex-wrap items-center gap-3 text-sm">
              <span className="font-semibold text-brand-900">
                เลือก {selectedIds.size} คน
              </span>
              <span className="text-ink-400">→</span>
              <span className="text-ink-600">เปลี่ยน role เป็น</span>
              <select
                value={bulkRole}
                onChange={(e) => setBulkRole(e.target.value)}
                className="px-2 py-1 rounded border border-brand-300 text-sm bg-white font-mono"
              >
                <option value="">— เลือก —</option>
                {(sub.allowed_roles && sub.allowed_roles.length > 0
                  ? sub.allowed_roles
                  : ["user"]
                ).map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
              <button
                onClick={applyBulkRole}
                disabled={bulkBusy || !bulkRole}
                className="px-3 py-1 rounded bg-brand-600 hover:bg-brand-700 text-white text-xs font-semibold disabled:opacity-50"
              >
                {bulkBusy ? "…" : "ใช้กับทั้งหมด"}
              </button>
              <button
                onClick={clearSelection}
                className="px-3 py-1 rounded border border-ink-200 hover:bg-white text-xs font-medium text-ink-700"
              >
                ยกเลิก
              </button>
              <button
                onClick={selectAll}
                className="text-xs text-brand-600 hover:text-brand-700 underline ml-auto"
              >
                เลือกทั้งหมด ({whitelist?.length || 0})
              </button>
            </div>
          )}

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
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider">
              Audit · กิจกรรมที่เกิดกับ subsystem นี้{" "}
              <span className="text-ink-400 font-normal">
                · {auditTotal.toLocaleString("en-US")} รายการ
              </span>
            </h3>
            {auditTotal > AUDIT_PAGE && (
              <div className="flex items-center gap-2 text-xs">
                <button
                  onClick={() => loadAudit(Math.max(0, auditOffset - AUDIT_PAGE))}
                  disabled={auditOffset === 0}
                  className="px-2 py-1 rounded border border-ink-200 hover:bg-ink-50 disabled:opacity-40"
                >
                  ← ก่อนหน้า
                </button>
                <span className="text-ink-500 font-mono">
                  {auditOffset + 1}–
                  {Math.min(auditOffset + AUDIT_PAGE, auditTotal)} /{" "}
                  {auditTotal}
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
          </div>
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

      {/* ── Revoke level dropdown (floating, escapes table overflow) ── */}
      {revokeMenuFor && revokeMenuPos && (() => {
        const session = active?.sessions.find(
          (x) => x.session_id === revokeMenuFor
        );
        const email = session?.user_email || null;
        return (
          <>
            <div
              className="fixed inset-0 z-[60]"
              onClick={() => setRevokeMenuFor(null)}
            />
            <div
              className="fixed w-72 bg-white rounded-lg shadow-xl border border-ink-200 z-[70] text-left"
              style={{ top: revokeMenuPos.top, right: revokeMenuPos.right }}
            >
              <button
                onClick={() =>
                  revokeSession(revokeMenuFor, email, "notify")
                }
                className="w-full px-3 py-2 hover:bg-amber-50 border-b border-ink-100 text-left"
              >
                <div className="text-[12px] font-bold text-amber-700">
                  📧 Notify only
                </div>
                <div className="text-[10px] text-ink-500 mt-0.5">
                  เตะออก + email แจ้ง · login ใหม่ได้ทันที
                </div>
              </button>
              <button
                onClick={() =>
                  revokeSession(revokeMenuFor, email, "challenge")
                }
                className="w-full px-3 py-2 hover:bg-rose-50 border-b border-ink-100 text-left"
              >
                <div className="text-[12px] font-bold text-rose-700">
                  🔒 Require email confirm
                </div>
                <div className="text-[10px] text-ink-500 mt-0.5">
                  ต้องคลิก link ใน email ก่อน login ใหม่ (15 นาที)
                </div>
              </button>
              <button
                onClick={() => revokeSession(revokeMenuFor, email, "ban")}
                className="w-full px-3 py-2 hover:bg-ink-100 text-left"
              >
                <div className="text-[12px] font-bold text-ink-900">
                  🛑 Revoke + Ban
                </div>
                <div className="text-[10px] text-ink-500 mt-0.5">
                  ลบจาก whitelist · login ใหม่ไม่ได้
                </div>
              </button>
            </div>
          </>
        );
      })()}

      {/* ── Transfer owner modal ──────────────────────── */}
      {transferOpen && (
        <div
          className="fixed inset-0 bg-ink-900/40 z-50 flex items-center justify-center p-4"
          onClick={() => !transferBusy && setTransferOpen(false)}
        >
          <div
            className="bg-white rounded-xl shadow-xl max-w-md w-full"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-6 py-4 border-b border-ink-100">
              <h3 className="text-lg font-extrabold text-ink-900">
                โอน ownership
              </h3>
              <p className="text-xs text-ink-500 mt-1">
                เจ้าของใหม่ต้องเป็น <strong>teacher / staff / admin</strong>{" "}
                และ login เข้าระบบมาก่อน
              </p>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <FieldLabel>อีเมลของเจ้าของใหม่</FieldLabel>
                <input
                  type="email"
                  placeholder="newowner@uni.ac.th"
                  value={transferEmail}
                  onChange={(e) => setTransferEmail(e.target.value)}
                  autoFocus
                  className="w-full px-3 py-2 rounded-lg border border-ink-200 text-sm focus:outline-none focus:border-brand-500"
                />
              </div>
              <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3">
                ⚠ หลังโอนแล้ว <strong>คุณจะเข้าหน้านี้ไม่ได้</strong> —
                เจ้าของใหม่จะจัดการ whitelist แทน
              </div>
            </div>
            <div className="px-6 py-4 border-t border-ink-100 flex justify-end gap-2">
              <button
                onClick={() => setTransferOpen(false)}
                disabled={transferBusy}
                className="px-4 py-2 rounded-lg border border-ink-200 hover:bg-ink-50 text-sm font-medium text-ink-700 disabled:opacity-50"
              >
                ยกเลิก
              </button>
              <button
                onClick={submitTransfer}
                disabled={transferBusy || !transferEmail.trim()}
                className="px-4 py-2 rounded-lg bg-rose-600 hover:bg-rose-700 text-white text-sm font-semibold disabled:opacity-50"
              >
                {transferBusy ? "กำลังโอน…" : "ยืนยันโอน"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Rotate secret result modal ─────────────────── */}
      {rotateResult && (() => {
        const viaEmail = rotateResult.secret_delivery === "email"; // pragma: allowlist secret
        return (
        <div
          className="fixed inset-0 bg-ink-900/40 z-50 flex items-center justify-center p-4"
          onClick={() => setRotateResult(null)}
        >
          <div
            className="bg-white rounded-xl shadow-xl max-w-xl w-full"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-6 py-4 border-b border-ink-100 flex items-center justify-between">
              <h3 className="text-lg font-extrabold text-ink-900">
                🔑 Rotate Secret สำเร็จ
              </h3>
              <button
                onClick={() => setRotateResult(null)}
                className="text-ink-400 hover:text-ink-700 text-xl"
              >
                ✕
              </button>
            </div>
            <div className="p-6 space-y-4 text-sm">
              <p className="text-ink-700">{rotateResult.message}</p>
              {viaEmail ? (
                <div className="rounded-lg bg-brand-50 border border-brand-200 p-4">
                  📧 ลิงก์ดู client_secret ส่งไปที่{" "}
                  <strong>{rotateResult.secret_sent_to}</strong> — ใช้ได้ครั้งเดียว
                  หมดอายุใน 15 นาที
                </div>
              ) : (
                <div className="rounded-lg bg-rose-50 border border-rose-200 p-4 space-y-2">
                  <div className="text-rose-700 text-xs">
                    ⚠ Email ส่งไม่สำเร็จ — copy ลิงก์นี้เปิดในเบราว์เซอร์ทันที
                  </div>
                  <div className="bg-white border border-rose-200 rounded p-3 font-mono text-[11px] break-all">
                    {rotateResult.secret_retrieval_url}
                  </div>
                  <a
                    href={rotateResult.secret_retrieval_url || "#"}
                    target="_blank"
                    rel="noopener"
                    className="inline-block px-4 py-2 rounded-lg bg-rose-600 hover:bg-rose-700 text-white text-sm font-semibold"
                  >
                    เปิดลิงก์ในแท็บใหม่ →
                  </a>
                </div>
              )}
              <div className="text-xs text-ink-500 border-t border-ink-100 pt-3">
                Secret เก่ายังใช้ได้อีก{" "}
                <strong>{rotateResult.grace_hours} ชั่วโมง</strong> — หมดอายุ{" "}
                <span className="font-mono">
                  {parseUTC(rotateResult.previous_expires_at).toLocaleString(
                    "th-TH",
                    {
                      timeZone: "Asia/Bangkok",
                      dateStyle: "short",
                      timeStyle: "short",
                    }
                  )}
                </span>
              </div>
            </div>
          </div>
        </div>
        );
      })()}

      {/* ── Edit subsystem modal ─────────────────────────── */}
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
              <div>
                <FieldLabel>คำอธิบาย</FieldLabel>
                <textarea
                  value={editDesc}
                  onChange={(e) => setEditDesc(e.target.value)}
                  rows={3}
                  className="w-full px-3 py-2 rounded-lg border border-ink-200 text-sm focus:outline-none focus:border-brand-500"
                />
              </div>
              <div>
                <FieldLabel>Redirect URIs (1 บรรทัด/URL)</FieldLabel>
                <textarea
                  value={editRedirects}
                  onChange={(e) => setEditRedirects(e.target.value)}
                  rows={4}
                  placeholder="http://localhost:8001/oauth/callback"
                  className="w-full px-3 py-2 rounded-lg border border-ink-200 font-mono text-[12px] focus:outline-none focus:border-brand-500"
                />
              </div>
              <div>
                <FieldLabel>
                  Scope ·{" "}
                  <span className="text-amber-700 normal-case">
                    ⚠ ขยาย scope = ต้อง re-approve
                  </span>
                </FieldLabel>
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
                        <div className="flex-1">
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
                <FieldLabel>
                  Allowed Roles ใน subsystem (คั่นด้วย comma)
                </FieldLabel>
                <input
                  value={editAllowedRoles}
                  onChange={(e) => setEditAllowedRoles(e.target.value)}
                  placeholder="resident, teacher, staff"
                  className="w-full px-3 py-2 rounded-lg border border-ink-200 font-mono text-[12px] focus:outline-none focus:border-brand-500"
                />
                <div className="text-[10px] text-ink-400 mt-1">
                  ใช้ตรวจสอบเวลาเพิ่ม user เข้า whitelist · ตัด role ที่ยังถูกใช้อยู่ไม่ได้
                </div>
              </div>
              <div>
                <FieldLabel>
                  Webhook URL ของ subsystem ·{" "}
                  <span className="text-ink-400 normal-case">(advanced — ปล่อยว่างได้)</span>
                </FieldLabel>
                <input
                  value={editWebhookUrl}
                  onChange={(e) => setEditWebhookUrl(e.target.value)}
                  placeholder="ปล่อยว่าง = ใช้ http://{redirect_uri[0] origin}/internal/access-revoked"
                  className="w-full px-3 py-2 rounded-lg border border-ink-200 font-mono text-[12px] focus:outline-none focus:border-brand-500"
                />
                <div className="text-[10px] text-ink-500 mt-1.5 leading-relaxed">
                  URL ฝั่ง <strong>subsystem</strong> ที่ Hub จะยิง POST เข้าไป
                  ตอน admin Revoke user เพื่อสั่ง subsystem ปิด session ทันที
                  <br />
                  <span className="text-ink-400">
                    ส่วนใหญ่ปล่อยว่าง — Hub auto-derive จาก redirect_uri[0]
                    + auto-translate <code>localhost</code> → docker service name ใน dev
                  </span>
                </div>
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
                onClick={saveEditSubsystem}
                disabled={editBusy}
                className="px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-700 text-white text-sm font-semibold disabled:opacity-50"
              >
                {editBusy ? "กำลังบันทึก…" : "บันทึก"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Audit detail slide panel ── */}
      <SlidePanel
        open={!!selectedAudit}
        onClose={() => setSelectedAudit(null)}
        title="รายละเอียด Audit Log"
      >
        {selectedAudit && (
          <AuditDetailBody
            entry={selectedAudit}
            labelFor={labelFor}
            detailFor={detailFor}
          />
        )}
      </SlidePanel>
    </>
  );
}

function AuditRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-1 border-b border-ink-100 last:border-b-0">
      <span className="text-[11px] text-ink-500 shrink-0">{label}</span>
      <span className="text-right">{children}</span>
    </div>
  );
}

function AuditDetailBody({
  entry,
  labelFor,
  detailFor,
}: {
  entry: AuditItem;
  labelFor: (a: string) => string;
  detailFor: (a: AuditItem) => string;
}) {
  const m = (entry.metadata || {}) as Record<string, unknown>;
  const metaKeys = Object.keys(m);

  const time = entry.created_at
    ? parseUTC(entry.created_at).toLocaleString("th-TH", {
        timeZone: "Asia/Bangkok",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      })
    : "—";

  // ตัด key พิเศษบางตัวมา highlight แยก
  const userEmail = m.user_email as string | undefined;
  const userName = m.user_full_name as string | undefined;
  const userId = m.user_id as string | undefined;
  const level = m.level as string | undefined;
  const wd = m.webhook_delivered as boolean | null | undefined;
  const jtiRevoked = m.jti_revoked as boolean | undefined;
  const summary = detailFor(entry);

  return (
    <div className="space-y-5 text-sm">
      {/* Header */}
      <div>
        <div className="text-xs text-ink-500 mb-1">Action</div>
        <div className="text-base font-extrabold text-ink-900">
          {labelFor(entry.action)}
        </div>
        <div className="font-mono text-[11px] text-ink-400 mt-0.5">
          {entry.action}
        </div>
      </div>

      {/* Summary chip */}
      {summary && summary !== "—" && (
        <div className="rounded-lg bg-ink-50 border border-ink-200 px-3 py-2 text-xs text-ink-700">
          {summary}
        </div>
      )}

      {/* Quick facts */}
      <div className="grid grid-cols-1 gap-2">
        <AuditRow label="เวลา (Asia/Bangkok)">
          <span className="font-mono text-xs">{time}</span>
        </AuditRow>
        <AuditRow label="ผู้กระทำ (actor)">
          <span className="text-xs">{entry.actor_email || "—"}</span>
        </AuditRow>
        <AuditRow label="Role">
          {entry.actor_is_hub_admin ? (
            <Badge tone="danger">Hub Admin</Badge>
          ) : entry.actor_user_type ? (
            <Badge
              tone={
                entry.actor_user_type === "admin"
                  ? "danger"
                  : entry.actor_user_type === "staff"
                  ? "warn"
                  : entry.actor_user_type === "teacher"
                  ? "brand"
                  : "default"
              }
            >
              {entry.actor_user_type}
            </Badge>
          ) : (
            <span className="text-xs text-ink-400 italic">system</span>
          )}
        </AuditRow>
        <AuditRow label="IP">
          <span className="font-mono text-xs">{entry.ip || "—"}</span>
        </AuditRow>
        <AuditRow label="Target">
          <span className="text-xs">
            <span className="font-mono">{entry.target_type}</span>
            {entry.target_id && (
              <span className="text-ink-500"> · {entry.target_id.slice(0, 12)}…</span>
            )}
          </span>
        </AuditRow>
      </div>

      {/* User target (ถ้ามี) */}
      {(userEmail || userName || userId) && (
        <div>
          <div className="text-xs font-bold text-ink-900 mb-2">👤 ผู้ใช้ที่เป็นเป้าหมาย</div>
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 space-y-1.5">
            {userName && (
              <div className="text-xs">
                <span className="text-ink-500">ชื่อ:</span>{" "}
                <span className="font-semibold text-ink-900">{userName}</span>
              </div>
            )}
            {userEmail && (
              <div className="text-xs">
                <span className="text-ink-500">Email:</span>{" "}
                <span className="font-mono text-ink-900">{userEmail}</span>
              </div>
            )}
            {userId && (
              <div className="text-xs">
                <span className="text-ink-500">User ID:</span>{" "}
                <span className="font-mono text-ink-700">{userId}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Outcome (force-revoke specific) */}
      {entry.action.startsWith("user_force_revoked_") && (
        <div>
          <div className="text-xs font-bold text-ink-900 mb-2">🚨 ผลการเตะ</div>
          <div className="grid grid-cols-1 gap-2">
            {level && (
              <AuditRow label="ระดับ">
                <Badge
                  tone={
                    level === "ban"
                      ? "danger"
                      : level === "challenge"
                      ? "warn"
                      : "brand"
                  }
                >
                  {level.toUpperCase()}
                </Badge>
              </AuditRow>
            )}
            <AuditRow label="JWT ถูกบล็อก (jti revoked)">
              <BoolPill v={jtiRevoked} />
            </AuditRow>
            <AuditRow label="Webhook ส่งถึง subsystem">
              <BoolPill v={wd} unknownLabel="ไม่ได้ยิง" />
            </AuditRow>
            {m.whitelist_removed === true && (
              <AuditRow label="ลบจาก whitelist">
                <BoolPill v={true} />
              </AuditRow>
            )}
            {m.challenge_created === true && (
              <AuditRow label="สร้าง identity challenge">
                <BoolPill v={true} />
              </AuditRow>
            )}
          </div>
        </div>
      )}

      {/* Raw metadata (collapsible-ish) */}
      {metaKeys.length > 0 && (
        <details className="rounded-lg border border-ink-200 bg-ink-50 group">
          <summary className="px-3 py-2 cursor-pointer text-xs font-semibold text-ink-700 hover:text-ink-900 list-none flex items-center justify-between">
            <span>📋 Raw metadata ({metaKeys.length} fields)</span>
            <span className="text-ink-400 group-open:rotate-90 transition-transform">▶</span>
          </summary>
          <pre className="px-3 py-2 border-t border-ink-200 bg-white text-[10px] font-mono text-ink-700 overflow-x-auto whitespace-pre-wrap break-all max-h-80 overflow-y-auto">
            {JSON.stringify(m, null, 2)}
          </pre>
        </details>
      )}

      {/* IDs */}
      <div className="border-t border-ink-200 pt-3 text-[10px] text-ink-400 font-mono space-y-0.5">
        <div>audit_log_id: {entry.id}</div>
        {entry.actor_id && <div>actor_id: {entry.actor_id}</div>}
      </div>
    </div>
  );
}

function BoolPill({
  v,
  unknownLabel = "—",
}: {
  v: boolean | null | undefined;
  unknownLabel?: string;
}) {
  if (v === true)
    return (
      <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700">
        ✓ สำเร็จ
      </span>
    );
  if (v === false)
    return (
      <span className="inline-flex items-center gap-1 text-xs font-semibold text-rose-700">
        ✗ ไม่สำเร็จ
      </span>
    );
  return <span className="text-xs text-ink-400">{unknownLabel}</span>;
}

function KpiCard({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "brand" | "good" | "danger";
}) {
  const toneClass =
    tone === "brand"
      ? "border-brand-200 bg-brand-50/40"
      : tone === "good"
      ? "border-emerald-200 bg-emerald-50/40"
      : tone === "danger"
      ? "border-rose-200 bg-rose-50/40"
      : "border-ink-200 bg-white";
  const valueClass =
    tone === "brand"
      ? "text-brand-700"
      : tone === "good"
      ? "text-emerald-700"
      : tone === "danger"
      ? "text-rose-700"
      : "text-ink-900";
  return (
    <div className={`rounded-xl border p-4 ${toneClass}`}>
      <div className="text-[10px] font-bold uppercase tracking-wider text-ink-500">
        {label}
      </div>
      <div className={`text-2xl font-extrabold tabular-nums mt-1 ${valueClass}`}>
        {value}
      </div>
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

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[11px] font-bold text-ink-500 uppercase tracking-wider mb-1.5">
      {children}
    </div>
  );
}
