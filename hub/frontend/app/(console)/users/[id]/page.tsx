"use client";

/**
 * User 360° View — หน้าเต็มข้อมูลผู้ใช้แบบครบวงจร.
 * Profile + Risk sparkline · stat cards · Subsystems & Access (+grant/revoke) ·
 * Recent Login & Risk · Quick Actions (passkey/edit/delete/logout) · Passkeys &
 * MFA · Active Sessions · Access Overview (scope donut) · Risk Factors.
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Topbar } from "@/components/Topbar";
import { Badge } from "@/components/Badge";
import {
  adminGetUserAccessList,
  adminGetUserLoginSessions,
  adminGetUserSummary,
  adminListUserPasskeys,
  adminResetUserPasskeys,
  adminRevokeUserAccess,
  adminGrantUserAccess,
  adminForceLogoutUser,
  adminDeleteUser,
  adminGetUserCredentials,
  type CredentialList,
  type UserAccessList,
  type UserLoginSessions,
  type UserSummary,
  type AdminUserPasskeys,
} from "@/lib/passkey";
import { UserFormModal, type UserRow } from "../_components/UserFormModal";
import { parseUTC, relTime } from "@/lib/format";

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

// scope → หมวด (สำหรับ donut Access Overview) — scope จริงเป็นชื่อฟิลด์ PII
const SCOPE_CAT: { key: string; label: string; color: string; match: string[] }[] = [
  { key: "identity", label: "ระบุตัวตน", color: "#2f6feb", match: ["name", "student_id", "employee_id"] },
  { key: "contact", label: "ติดต่อ", color: "#10b981", match: ["email", "phone", "address"] },
  { key: "academic", label: "วิชาการ", color: "#f59e0b", match: ["faculty", "major", "year", "position"] },
];
function scopeCat(scope: string): string {
  for (const c of SCOPE_CAT) if (c.match.includes(scope)) return c.key;
  return "other";
}

// parseUTC + relTime ย้ายไป lib/format.ts (canonical + unit-tested — กันบั๊ก B53)

function riskLabel(score: number | null): { text: string; tone: string; dot: string } {
  if (score === null) return { text: "—", tone: "bg-ink-100 text-ink-500", dot: "#cbd5e1" };
  if (score >= 0.85) return { text: "Block", tone: "bg-red-100 text-red-700", dot: "#dc2626" };
  if (score >= 0.5) return { text: "High", tone: "bg-amber-100 text-amber-700", dot: "#f59e0b" };
  if (score >= 0.4) return { text: "Warn", tone: "bg-yellow-100 text-yellow-700", dot: "#eab308" };
  return { text: "Low", tone: "bg-emerald-100 text-emerald-700", dot: "#10b981" };
}

/** Sparkline SVG จาก risk scores (เก่า→ใหม่) */
function Sparkline({ data }: { data: number[] }) {
  const w = 220;
  const h = 56;
  if (data.length < 2)
    return <div className="text-xs text-ink-300 h-14 grid place-items-center">ข้อมูลไม่พอวาดกราฟ</div>;
  const max = 1;
  const step = w / (data.length - 1);
  const pts = data.map((v, i) => `${i * step},${h - (v / max) * h}`).join(" ");
  const last = data[data.length - 1];
  const color = riskLabel(last).dot;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-14" preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={(data.length - 1) * step} cy={h - (last / max) * h} r="3" fill={color} />
    </svg>
  );
}

/** Donut SVG (stroke-dasharray segments) */
function Donut({ segments, total }: { segments: { label: string; value: number; color: string }[]; total: number }) {
  const r = 42;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <svg viewBox="0 0 120 120" className="w-32 h-32">
      <circle cx="60" cy="60" r={r} fill="none" stroke="#f1f5f9" strokeWidth="14" />
      {segments.map((s) => {
        const frac = total ? s.value / total : 0;
        const dash = frac * c;
        const el = (
          <circle
            key={s.label}
            cx="60"
            cy="60"
            r={r}
            fill="none"
            stroke={s.color}
            strokeWidth="14"
            strokeDasharray={`${dash} ${c - dash}`}
            strokeDashoffset={-offset}
            transform="rotate(-90 60 60)"
          />
        );
        offset += dash;
        return el;
      })}
      <text x="60" y="56" textAnchor="middle" className="fill-ink-900 font-extrabold" fontSize="22">
        {total}
      </text>
      <text x="60" y="72" textAnchor="middle" className="fill-ink-400" fontSize="8">
        scopes
      </text>
    </svg>
  );
}

function StatCard({ label, value, sub, accent }: { label: string; value: ReactNode; sub?: string; accent?: string }) {
  return (
    <div className="bg-white rounded-xl border border-ink-200 p-4 shadow-sm">
      <div className="text-[11px] text-ink-500 uppercase tracking-wider">{label}</div>
      <div className={`text-2xl font-extrabold mt-1 ${accent || "text-ink-900"}`}>
        {value}
        {sub && <span className="text-xs font-normal text-ink-400 ml-1">{sub}</span>}
      </div>
    </div>
  );
}

export default function UserDetailPage({ params }: { params: { id: string } }) {
  const id = params.id;
  const router = useRouter();

  const [access, setAccess] = useState<UserAccessList | null>(null);
  const [history, setHistory] = useState<UserLoginSessions | null>(null);
  const [passkeys, setPasskeys] = useState<AdminUserPasskeys | null>(null);
  const [summary, setSummary] = useState<UserSummary | null>(null);
  const [creds, setCreds] = useState<CredentialList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [grantSel, setGrantSel] = useState("");
  const [addrExpanded, setAddrExpanded] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      adminGetUserAccessList(id),
      adminGetUserLoginSessions(id).catch(() => null),
      adminListUserPasskeys(id).catch(() => null),
      adminGetUserSummary(id).catch(() => null),
      adminGetUserCredentials(id).catch(() => null),
    ])
      .then(([a, h, p, s, c]) => {
        setAccess(a);
        setHistory(h);
        setPasskeys(p);
        setSummary(s);
        setCreds(c);
      })
      .catch((e) => setError(e?.detail || "โหลดไม่สำเร็จ"))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(load, [load]);

  const errMsg = (e: unknown, fb: string) =>
    typeof e === "object" && e && "detail" in e
      ? String((e as { detail: unknown }).detail)
      : fb;

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(errMsg(e, "ทำรายการไม่สำเร็จ"));
    } finally {
      setBusy(null);
    }
  };

  const revoke = (subId: string, name: string) =>
    confirm(
      `ถอนสิทธิ์ "${name}"?\nผู้ใช้จะเข้าระบบนี้ไม่ได้ (แม้เข้าได้ตามนโยบาย) ` +
        `และ session ที่เปิดอยู่จะถูกปิด — คืนสิทธิ์ได้ภายหลังด้วยปุ่ม "เพิ่มสิทธิ์"`,
    ) &&
    run("revoke:" + subId, async () => {
      const r = await adminRevokeUserAccess(id, subId, setVerifying);
      alert(`ถอนสิทธิ์แล้ว · ปิด ${r.closed_sessions} session`);
      load();
    });

  const grant = () =>
    grantSel &&
    run("grant", async () => {
      const r = await adminGrantUserAccess(id, grantSel, setVerifying);
      alert(`เพิ่มสิทธิ์ "${r.subsystem_name}" แล้ว`);
      setGrantSel("");
      load();
    });

  const forceLogout = () =>
    confirm("บังคับ logout ทุกอุปกรณ์ของผู้ใช้นี้?") &&
    run("logout", async () => {
      const r = await adminForceLogoutUser(id, setVerifying);
      alert(`ปิด ${r.closed_sessions} session · revoke ${r.revoked_jwt} token`);
      load();
    });

  const resetPasskeys = () =>
    confirm("Reset passkey ทั้งหมด? ผู้ใช้ต้องตั้งค่าใหม่") &&
    run("reset", async () => {
      const r = await adminResetUserPasskeys(id, setVerifying);
      alert(r.message);
      load();
    });

  const removeUser = () =>
    u &&
    confirm(`ลบผู้ใช้ "${u.full_name}"? บัญชีจะถูกตั้งเป็น deleted`) &&
    run("delete", async () => {
      await adminDeleteUser(id, setVerifying);
      alert("ลบผู้ใช้แล้ว");
      router.push("/users");
    });

  // ── derived ──
  const u = access?.user;
  const subsystems = access?.subsystems ?? [];
  const sessions = history?.sessions ?? [];
  const currentRisk = sessions[0]?.risk_score ?? summary?.last_risk_event?.risk_score ?? null;
  const risk = riskLabel(currentRisk);
  const activeSessions = sessions.filter((s) => s.online);
  const sparkData = sessions
    .filter((s) => s.risk_score !== null)
    .slice(0, 12)
    .reverse()
    .map((s) => s.risk_score as number);
  const roles = Array.from(new Set(subsystems.map((s) => s.role).filter(Boolean)));
  const allScopes = Array.from(new Set(subsystems.flatMap((s) => s.scopes)));
  const donutSegs = SCOPE_CAT.map((c) => ({
    label: c.label,
    color: c.color,
    value: allScopes.filter((sc) => scopeCat(sc) === c.key).length,
  }));
  const otherCount = allScopes.filter((sc) => scopeCat(sc) === "other").length;
  if (otherCount) donutSegs.push({ label: "อื่นๆ", color: "#8b5cf6", value: otherCount });
  const riskFactors = sessions[0]?.risk_reasons ?? [];
  const initial = (u?.full_name || u?.email || "?").charAt(0).toUpperCase();

  return (
    <>
      <Topbar title="User 360° View" />
      {verifying && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-2xl px-6 py-5 shadow-xl flex items-center gap-3 text-sm text-ink-700">
            <span className="animate-pulse text-lg">🔐</span>
            กำลังยืนยันด้วย Passkey…
          </div>
        </div>
      )}

      <main className="p-6 md:p-8 max-w-[1200px] mx-auto w-full space-y-5">
        {/* breadcrumb */}
        <div className="text-sm text-ink-500 flex items-center gap-2">
          <Link href="/users" className="hover:text-brand-600">
            ผู้ใช้งาน
          </Link>
          <span>/</span>
          <span className="text-ink-800 font-medium">{u?.full_name || "…"}</span>
          <span>/</span>
          <span className="text-ink-400">360° View</span>
        </div>

        {/* title row */}
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-extrabold text-ink-900">User 360° View</h1>
            <p className="text-sm text-ink-500">ภาพรวมข้อมูลผู้ใช้แบบครบวงจร</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={forceLogout}
              disabled={busy === "logout" || activeSessions.length === 0}
              className="px-3 py-2 rounded-lg border border-ink-200 text-sm font-medium hover:bg-ink-50 disabled:opacity-40"
            >
              🚪 Force Logout ทั้งหมด
            </button>
            <button
              onClick={removeUser}
              disabled={busy === "delete" || u?.status === "deleted"}
              className="px-3 py-2 rounded-lg border border-red-300 text-red-700 text-sm font-medium hover:bg-red-50 disabled:opacity-40"
            >
              🗑️ ลบผู้ใช้
            </button>
            <button
              onClick={() => setEditOpen(true)}
              className="px-3 py-2 rounded-lg bg-brand-600 text-white text-sm font-semibold hover:bg-brand-700"
            >
              ✏️ แก้ไขผู้ใช้
            </button>
          </div>
        </div>

        {error && (
          <div className="p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm">
            {error}
          </div>
        )}

        {loading ? (
          <div className="text-center text-ink-400 py-20">กำลังโหลด…</div>
        ) : !u ? (
          <div className="text-center text-ink-400 py-20">ไม่พบผู้ใช้</div>
        ) : (
          <>
            {/* ── Profile + Risk ── */}
            <section className="bg-white rounded-xl border border-ink-200 p-6 shadow-sm grid md:grid-cols-3 gap-6">
              <div className="md:col-span-2 flex items-start gap-4">
                <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 grid place-items-center text-white text-3xl font-extrabold shrink-0">
                  {initial}
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h2 className="text-2xl font-extrabold text-ink-900">{u.full_name}</h2>
                    {u.is_hub_admin ? (
                      <Badge tone="danger">ADMIN</Badge>
                    ) : (
                      <Badge tone={TYPE_TONE[u.user_type || ""] || "default"}>{u.user_type}</Badge>
                    )}
                    <Badge tone={STATUS_TONE[u.status || ""] || "default"}>{u.status}</Badge>
                  </div>
                  <div className="text-sm text-ink-500 font-mono mt-0.5">{u.email}</div>
                  <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-2.5 mt-4 text-xs">
                    {[
                      ["รหัส / User ID", u.identifier || u.id.slice(0, 8)],
                      ["ประเภทผู้ใช้", u.is_hub_admin ? "Hub Admin" : u.user_type || "—"],
                      ["คณะ / หน่วยงาน", u.faculty || "—"],
                      ["สาขา / ตำแหน่ง", u.major || u.year_or_position || "—"],
                      ["เบอร์โทร", u.phone || "—"],
                      ["สร้างเมื่อ", relTime(u.created_at)],
                      ["Login ล่าสุด", relTime(summary?.last_login_at || sessions[0]?.created_at || null)],
                      ["Passkey / MFA", `${passkeys?.count ?? 0} รายการ`],
                      ["Backup codes", `${passkeys?.backup_codes.remaining ?? 0}/${passkeys?.backup_codes.total ?? 0}`],
                    ].map(([k, v]) => (
                      <div key={k} className="min-w-0">
                        <dt className="text-ink-400">{k}</dt>
                        <dd className="text-ink-800 font-medium truncate" title={v || undefined}>
                          {v}
                        </dd>
                      </div>
                    ))}
                    <div className="min-w-0 col-span-2">
                      <dt className="text-ink-400">ที่อยู่</dt>
                      <dd
                        onDoubleClick={() => setAddrExpanded((v) => !v)}
                        title={
                          u.address
                            ? addrExpanded
                              ? "ดับเบิลคลิกเพื่อย่อ"
                              : "ดับเบิลคลิกเพื่อดูทั้งหมด"
                            : undefined
                        }
                        className={`text-ink-800 font-medium cursor-pointer select-none ${
                          addrExpanded ? "whitespace-normal break-words" : "truncate"
                        }`}
                      >
                        {u.address || "—"}
                      </dd>
                    </div>
                  </dl>
                </div>
              </div>

              {/* Risk card */}
              <div className="rounded-xl bg-ink-50/60 border border-ink-100 p-4">
                <div className="text-xs text-ink-500 uppercase tracking-wider">
                  Current Risk Level
                </div>
                <div className="flex items-baseline gap-2 mt-1">
                  <span className={`px-2 py-0.5 rounded-md text-sm font-bold ${risk.tone}`}>
                    {risk.text}
                  </span>
                  <span className="text-2xl font-extrabold text-ink-900 font-mono">
                    {currentRisk !== null ? currentRisk.toFixed(2) : "—"}
                  </span>
                  <span className="text-xs text-ink-400">/ 1.00</span>
                </div>
                <Sparkline data={sparkData} />
                <div className="text-[11px] text-ink-400">
                  {sessions[0]?.created_at ? `อัปเดต ${relTime(sessions[0].created_at)}` : "ยังไม่มี session"}
                </div>
              </div>
            </section>

            {/* ── stat cards ── */}
            <section className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
              <StatCard label="สิทธิ์ระบบย่อย" value={access?.active_count ?? 0} sub="active" />
              <StatCard label="บทบาท" value={roles.length} sub="assigned" />
              <StatCard label="Scopes" value={allScopes.length} sub="granted" />
              <StatCard label="Session ออนไลน์" value={activeSessions.length} sub="ตอนนี้" />
              <StatCard
                label="Failed Logins (7d)"
                value={summary?.failed_logins_7d ?? 0}
                accent={(summary?.failed_logins_7d ?? 0) > 0 ? "text-red-600" : "text-ink-900"}
              />
              <StatCard
                label="Risk Event ล่าสุด"
                value={summary?.last_risk_event ? relTime(summary.last_risk_event.created_at) : "—"}
                sub={summary?.last_risk_event?.risk_score != null ? `${summary.last_risk_event.risk_score.toFixed(2)}` : undefined}
              />
            </section>

            {/* ── main 2-col ── */}
            <div className="grid lg:grid-cols-3 gap-5">
              {/* left */}
              <div className="lg:col-span-2 space-y-5">
                {/* Subsystems & Access */}
                <section className="bg-white rounded-xl border border-ink-200 shadow-sm">
                  <div className="px-5 py-4 border-b border-ink-100 flex items-center justify-between gap-3 flex-wrap">
                    <h3 className="text-sm font-bold text-ink-700 flex items-center gap-2">
                      สิทธิ์เข้าถึงระบบย่อย
                      <span className="text-ink-400 font-normal">({access?.active_count} ระบบ)</span>
                      <span className="text-ink-300 font-normal">·</span>
                      <span className="text-ink-400 font-normal">สถานะบัญชี</span>
                      <Badge tone={STATUS_TONE[u.status || ""] || "default"}>{u.status}</Badge>
                    </h3>
                    {access && access.grantable.length > 0 && (
                      <div className="flex items-center gap-2">
                        <select
                          value={grantSel}
                          onChange={(e) => setGrantSel(e.target.value)}
                          className="px-2.5 py-1.5 rounded-lg border border-ink-200 text-sm focus:outline-none focus:border-brand-500"
                        >
                          <option value="">+ เพิ่มสิทธิ์เข้าระบบ…</option>
                          {access.grantable.map((g) => (
                            <option key={g.subsystem_id} value={g.subsystem_id}>
                              {g.subsystem_name}
                            </option>
                          ))}
                        </select>
                        <button
                          onClick={grant}
                          disabled={!grantSel || busy === "grant"}
                          className="px-3 py-1.5 rounded-lg bg-brand-600 text-white text-sm font-semibold hover:bg-brand-700 disabled:opacity-40"
                        >
                          เพิ่ม
                        </button>
                      </div>
                    )}
                  </div>
                  {u.status !== "active" && (
                    <div className="mx-5 mt-3 px-3 py-2 rounded-lg bg-amber-50 border border-amber-200 text-[12px] text-amber-800">
                      บัญชีสถานะ <b>{u.status}</b> — ถูกบล็อกจากทุกระบบย่อยโดยอัตโนมัติ
                      (นโยบายทุกแบบต้องการสถานะ <code>active</code>) จนกว่าจะเปลี่ยนกลับเป็น active
                    </div>
                  )}
                  <div className="divide-y divide-ink-100">
                    {subsystems.length === 0 ? (
                      <div className="text-sm text-ink-500 text-center py-8">ยังไม่มีสิทธิ์เข้าระบบย่อยใด</div>
                    ) : (
                      subsystems.map((s) => (
                        <div key={s.subsystem_id} className="px-5 py-3 flex items-center gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="font-medium text-ink-900 flex items-center gap-2">
                              {s.subsystem_name}
                              {s.role && <Badge tone="brand">{s.role}</Badge>}
                              {s.source === "policy" && <Badge tone="default">นโยบาย</Badge>}
                            </div>
                            <div className="text-xs text-ink-500 mt-0.5">{s.reason}</div>
                            {s.scopes.length > 0 && (
                              <div className="flex flex-wrap gap-1 mt-1.5">
                                {s.scopes.slice(0, 5).map((sc) => (
                                  <span
                                    key={sc}
                                    className="text-[10px] px-1.5 py-0.5 rounded bg-ink-100 text-ink-600 font-mono"
                                  >
                                    {sc}
                                  </span>
                                ))}
                                {s.scopes.length > 5 && (
                                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-ink-50 text-ink-400">
                                    +{s.scopes.length - 5}
                                  </span>
                                )}
                              </div>
                            )}
                          </div>
                          {s.can_revoke ? (
                            <button
                              onClick={() => revoke(s.subsystem_id, s.subsystem_name)}
                              disabled={busy === "revoke:" + s.subsystem_id}
                              className="px-3 py-1.5 rounded-lg bg-red-600 text-white text-xs font-semibold hover:bg-red-700 disabled:opacity-50 shrink-0"
                            >
                              {busy === "revoke:" + s.subsystem_id ? "กำลังถอน…" : "ถอนสิทธิ์"}
                            </button>
                          ) : (
                            <span className="text-[11px] text-ink-400 shrink-0" title="เข้าได้ตามนโยบาย — ถอนรายคนไม่ได้">
                              ถอนรายคนไม่ได้
                            </span>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                </section>

                {/* Recent Login & Risk */}
                <section className="bg-white rounded-xl border border-ink-200 shadow-sm">
                  <div className="px-5 py-4 border-b border-ink-100">
                    <h3 className="text-sm font-bold text-ink-700">Recent Login &amp; Risk Events</h3>
                  </div>
                  <div className="divide-y divide-ink-100">
                    {sessions.length === 0 ? (
                      <div className="text-sm text-ink-500 text-center py-8">ยังไม่มีประวัติ</div>
                    ) : (
                      sessions.slice(0, 8).map((s) => {
                        const r = riskLabel(s.risk_score);
                        return (
                          <div key={s.id} className="px-5 py-2.5 flex items-center gap-3 text-xs">
                            <span
                              className="w-2 h-2 rounded-full shrink-0"
                              style={{ background: s.online ? "#10b981" : "#cbd5e1" }}
                            />
                            <div className="w-28 shrink-0 text-ink-400">{relTime(s.created_at)}</div>
                            <div className="flex-1 min-w-0">
                              <div className="font-medium text-ink-900 truncate">
                                {s.subsystem_name}
                                <span className="text-ink-400 font-normal"> · {s.login_method || "—"}</span>
                              </div>
                              <div className="text-ink-500 truncate">
                                {s.ip || "—"}
                                {s.geo_country && ` · ${s.geo_country}`}
                                {s.browser && ` · ${s.browser}`}
                              </div>
                            </div>
                            {s.risk_score !== null && (
                              <span className="font-mono text-ink-400">{s.risk_score.toFixed(2)}</span>
                            )}
                            {s.decision && (
                              <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold shrink-0 ${r.tone}`}>
                                {s.decision}
                              </span>
                            )}
                          </div>
                        );
                      })
                    )}
                  </div>
                </section>
              </div>

              {/* right */}
              <div className="space-y-5">
                {/* Quick Actions */}
                <section className="bg-white rounded-xl border border-ink-200 shadow-sm p-4">
                  <h3 className="text-sm font-bold text-ink-700 mb-3">Quick Actions</h3>
                  <div className="space-y-1.5">
                    {[
                      { label: "บังคับ Logout ทุกอุปกรณ์", desc: "ปิด session ทั้งหมด", onClick: forceLogout, disabled: activeSessions.length === 0, danger: false },
                      { label: "Reset Passkey", desc: "ลบ passkey ทั้งหมด", onClick: resetPasskeys, disabled: (passkeys?.count ?? 0) === 0, danger: false },
                      { label: "เปลี่ยนสถานะ / แก้ไข", desc: "ระงับ / เปิดใช้งาน", onClick: () => setEditOpen(true), disabled: false, danger: false },
                      { label: "ดู Audit Log", desc: "สิ่งที่ผู้ใช้นี้ทำเอง", onClick: () => router.push(`/audit?actor_id=${id}&actor_email=${encodeURIComponent(u.email)}`), disabled: false, danger: false },
                      { label: "ลบผู้ใช้", desc: "soft delete", onClick: removeUser, disabled: u.status === "deleted", danger: true },
                    ].map((a) => (
                      <button
                        key={a.label}
                        onClick={a.onClick}
                        disabled={a.disabled}
                        className={`w-full text-left px-3 py-2.5 rounded-lg border transition disabled:opacity-40 ${
                          a.danger
                            ? "border-red-200 hover:bg-red-50"
                            : "border-ink-100 hover:bg-ink-50"
                        }`}
                      >
                        <div className={`text-sm font-semibold ${a.danger ? "text-red-700" : "text-ink-800"}`}>
                          {a.label}
                        </div>
                        <div className="text-[11px] text-ink-400">{a.desc}</div>
                      </button>
                    ))}
                  </div>
                </section>

                {/* Passkeys & MFA */}
                <section className="bg-white rounded-xl border border-ink-200 shadow-sm">
                  <div className="px-4 py-3.5 border-b border-ink-100 flex items-center justify-between">
                    <h3 className="text-sm font-bold text-ink-700">Passkeys &amp; MFA</h3>
                    <span className="text-xs text-ink-400">{passkeys?.count ?? 0} รายการ</span>
                  </div>
                  <div className="p-4 space-y-2">
                    {!passkeys || passkeys.passkeys.length === 0 ? (
                      <div className="text-sm text-ink-500 text-center py-4">ยังไม่มี Passkey</div>
                    ) : (
                      passkeys.passkeys.map((pk) => (
                        <div key={pk.id} className="flex items-center gap-3 px-3 py-2 rounded-lg border border-ink-100">
                          <span className="text-lg">{pk.device_type === "platform" ? "💻" : "🔑"}</span>
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-medium text-ink-900 truncate">{pk.device_name}</div>
                            <div className="text-[11px] text-ink-400">ใช้ล่าสุด {relTime(pk.last_used_at)}</div>
                          </div>
                        </div>
                      ))
                    )}
                    <div className="flex items-center justify-between pt-2 text-xs">
                      <span className="text-ink-500">Backup codes</span>
                      <Badge tone={(passkeys?.backup_codes.remaining ?? 0) > 0 ? "good" : "warn"}>
                        เหลือ {passkeys?.backup_codes.remaining ?? 0}/{passkeys?.backup_codes.total ?? 0}
                      </Badge>
                    </div>
                  </div>
                </section>

                {/* Credential Management + Recovery Ready */}
                <section className="bg-white rounded-xl border border-ink-200 shadow-sm">
                  <div className="px-4 py-3.5 border-b border-ink-100 flex items-center justify-between">
                    <h3 className="text-sm font-bold text-ink-700">Authentication Methods</h3>
                    {creds && (
                      <Badge tone={creds.recovery_ready ? "good" : "warn"}>
                        {creds.recovery_ready ? "✓ Recovery Ready" : "⚠ ไม่พร้อมกู้"}
                      </Badge>
                    )}
                  </div>
                  <div className="p-4 space-y-1.5">
                    {!creds ? (
                      <div className="text-sm text-ink-400 text-center py-3">—</div>
                    ) : (
                      creds.credentials.map((c, i) => (
                        <div
                          key={c.id || `${c.credential_type}-${i}`}
                          className="flex items-center gap-2.5 px-3 py-2 rounded-lg border border-ink-100 text-xs"
                        >
                          <span className="text-base">
                            {c.credential_type === "GOOGLE"
                              ? "🔵"
                              : c.credential_type === "TOTP"
                                ? "🔐"
                                : "🔑"}
                          </span>
                          <div className="flex-1 min-w-0">
                            <div className="font-semibold text-ink-800 truncate">
                              {c.credential_type}{" "}
                              <span className="font-normal text-ink-400">{c.label}</span>
                            </div>
                          </div>
                          <Badge
                            tone={
                              c.status === "ACTIVE" || c.status === "verified"
                                ? "good"
                                : c.status === "SUSPENDED"
                                  ? "warn"
                                  : "default"
                            }
                          >
                            {c.status}
                          </Badge>
                        </div>
                      ))
                    )}
                  </div>
                </section>
              </div>
            </div>

            {/* ── bottom 3-col ── */}
            <div className="grid lg:grid-cols-3 gap-5">
              {/* Active Sessions */}
              <section className="bg-white rounded-xl border border-ink-200 shadow-sm p-4">
                <h3 className="text-sm font-bold text-ink-700 mb-3">
                  Active Sessions <span className="text-ink-400 font-normal">({activeSessions.length})</span>
                </h3>
                <div className="space-y-2">
                  {activeSessions.length === 0 ? (
                    <div className="text-sm text-ink-500 text-center py-4">ไม่มี session ออนไลน์</div>
                  ) : (
                    activeSessions.slice(0, 5).map((s) => (
                      <div key={s.id} className="flex items-center gap-3 px-3 py-2 rounded-lg border border-ink-100 text-xs">
                        <span className="text-lg">{s.device_type === "mobile" ? "📱" : "💻"}</span>
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-ink-900 truncate">
                            {s.browser || "—"} · {s.os_name || "—"}
                          </div>
                          <div className="text-ink-400 truncate">
                            {s.ip || "—"}
                            {s.geo_country && ` · ${s.geo_country}`} · {s.subsystem_name}
                          </div>
                        </div>
                        <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" />
                      </div>
                    ))
                  )}
                </div>
              </section>

              {/* Access Overview donut */}
              <section className="bg-white rounded-xl border border-ink-200 shadow-sm p-4">
                <h3 className="text-sm font-bold text-ink-700 mb-3">Access Overview</h3>
                <div className="flex items-center gap-4">
                  <Donut segments={donutSegs} total={allScopes.length} />
                  <div className="space-y-1.5 text-xs flex-1">
                    {donutSegs.map((seg) => (
                      <div key={seg.label} className="flex items-center gap-2">
                        <span className="w-2.5 h-2.5 rounded-full" style={{ background: seg.color }} />
                        <span className="text-ink-600 flex-1">{seg.label}</span>
                        <span className="text-ink-900 font-semibold">{seg.value}</span>
                        <span className="text-ink-400 w-9 text-right">
                          {allScopes.length ? Math.round((seg.value / allScopes.length) * 100) : 0}%
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </section>

              {/* Risk Factors */}
              <section className="bg-white rounded-xl border border-ink-200 shadow-sm p-4">
                <h3 className="text-sm font-bold text-ink-700 mb-3">
                  Risk Factors <span className="text-ink-400 font-normal">(login ล่าสุด)</span>
                </h3>
                <div className="space-y-2">
                  {riskFactors.length === 0 ? (
                    <div className="text-sm text-ink-500 text-center py-4">
                      ไม่มีปัจจัยเสี่ยง — session ล่าสุดปกติ
                    </div>
                  ) : (
                    riskFactors.slice(0, 5).map((rf, i) => (
                      <div key={i} className="flex items-center gap-2 px-3 py-2 rounded-lg border border-ink-100 text-xs">
                        <span className="text-amber-500">⚠</span>
                        <span className="text-ink-700 flex-1">{rf}</span>
                      </div>
                    ))
                  )}
                </div>
              </section>
            </div>
          </>
        )}
      </main>

      {editOpen && u && (
        <UserFormModal
          mode="edit"
          user={
            {
              id: u.id,
              email: u.email,
              full_name: u.full_name || "",
              user_type: u.user_type || "",
              identifier: u.identifier || undefined,
              faculty: u.faculty || undefined,
              major: u.major || undefined,
              year_or_position: u.year_or_position || undefined,
              phone: u.phone || undefined,
              status: u.status || undefined,
            } as UserRow
          }
          onClose={() => setEditOpen(false)}
          onSaved={() => {
            setEditOpen(false);
            load();
          }}
        />
      )}
    </>
  );
}
