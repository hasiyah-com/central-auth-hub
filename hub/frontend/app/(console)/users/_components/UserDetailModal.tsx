"use client";

/**
 * User Detail (360-degree view) modal — สิทธิ์ระบบย่อย + revoke + ประวัติ login.
 * เปิดจากหน้า Users (admin คลิก user). Revoke = critical action → step-up passkey.
 */

import { useCallback, useEffect, useState } from "react";
import {
  adminGetUserAccessList,
  adminGetUserLoginSessions,
  adminRevokeUserAccess,
  type UserAccessList,
  type UserLoginSessions,
} from "@/lib/passkey";

function relTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const day = Math.floor((Date.now() - d.getTime()) / 86400000);
  if (day < 1) return "วันนี้";
  if (day < 30) return `${day} วันก่อน`;
  return d.toLocaleDateString("th-TH");
}

type Props = {
  userId: string;
  userName: string;
  onClose: () => void;
};

export function UserDetailModal({ userId, userName, onClose }: Props) {
  const [access, setAccess] = useState<UserAccessList | null>(null);
  const [history, setHistory] = useState<UserLoginSessions | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      adminGetUserAccessList(userId),
      adminGetUserLoginSessions(userId).catch(() => null),
    ])
      .then(([a, h]) => {
        setAccess(a);
        setHistory(h);
      })
      .catch((e) => setError(e?.detail || "โหลดไม่สำเร็จ"))
      .finally(() => setLoading(false));
  }, [userId]);

  useEffect(load, [load]);

  const revoke = async (subsystemId: string, subsystemName: string) => {
    if (!confirm(`ถอนสิทธิ์ ${userName} จาก "${subsystemName}"? (session ที่เปิดอยู่จะถูกปิด)`))
      return;
    setRevoking(subsystemId);
    try {
      const r = await adminRevokeUserAccess(userId, subsystemId, setVerifying);
      alert(`ถอนสิทธิ์แล้ว · ปิด ${r.closed_sessions} session`);
      load();
    } catch (e) {
      setError(
        typeof e === "object" && e && "detail" in e
          ? String((e as { detail: unknown }).detail)
          : "ถอนสิทธิ์ไม่สำเร็จ"
      );
    } finally {
      setRevoking(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
      {verifying && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-2xl px-6 py-5 shadow-xl flex items-center gap-3 text-sm text-ink-700">
            <span className="animate-pulse text-lg">🔐</span>
            กำลังยืนยันด้วย Passkey…
          </div>
        </div>
      )}
      <div className="bg-white rounded-xl shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between sticky top-0 bg-white">
          <div>
            <h2 className="text-lg font-bold text-gray-900">ข้อมูลผู้ใช้ (360°)</h2>
            <p className="text-xs text-gray-500 font-mono">{userName}</p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700 text-xl"
          >
            ✕
          </button>
        </div>

        <div className="px-6 py-5 space-y-6">
          {loading ? (
            <div className="text-sm text-gray-400 text-center py-6">กำลังโหลด…</div>
          ) : error ? (
            <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {error}
            </div>
          ) : (
            <>
              {/* ── สิทธิ์เข้าถึงระบบย่อย ── */}
              <section>
                <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">
                  สิทธิ์เข้าถึงระบบย่อย
                  {access && (
                    <span className="ml-2 text-gray-400 normal-case font-normal">
                      ({access.active_count} active / {access.total} ทั้งหมด)
                    </span>
                  )}
                </h3>
                {!access || access.subsystems.length === 0 ? (
                  <div className="text-sm text-gray-500 text-center py-5 border border-dashed border-gray-200 rounded-lg">
                    ยังไม่มีสิทธิ์เข้าระบบย่อยใด
                  </div>
                ) : (
                  <div className="space-y-2">
                    {access.subsystems.map((s) => (
                      <div
                        key={s.subsystem_id + (s.revoked_at || "")}
                        className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border ${
                          s.active
                            ? "border-gray-200"
                            : "border-gray-100 bg-gray-50 opacity-70"
                        }`}
                      >
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-gray-900 truncate flex items-center gap-2">
                            {s.subsystem_name}
                            {s.entry_type === "deny" && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-100 text-red-700 font-bold">
                                DENY
                              </span>
                            )}
                            {!s.active && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-200 text-gray-600 font-bold">
                                ถอนแล้ว
                              </span>
                            )}
                          </div>
                          <div className="text-xs text-gray-500">
                            ให้สิทธิ์ {relTime(s.granted_at)}
                            {s.revoked_at && ` · ถอน ${relTime(s.revoked_at)}`}
                          </div>
                        </div>
                        {s.active && s.entry_type !== "deny" && (
                          <button
                            onClick={() => revoke(s.subsystem_id, s.subsystem_name)}
                            disabled={revoking === s.subsystem_id}
                            className="px-3 py-1.5 rounded-lg bg-red-600 text-white text-xs font-semibold hover:bg-red-700 disabled:opacity-50 shrink-0"
                          >
                            {revoking === s.subsystem_id ? "กำลังถอน…" : "ถอนสิทธิ์"}
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </section>

              {/* ── ประวัติ login เข้าระบบย่อยล่าสุด ── */}
              <section>
                <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">
                  ประวัติเข้าระบบย่อยล่าสุด
                </h3>
                {!history || history.sessions.length === 0 ? (
                  <div className="text-sm text-gray-500 text-center py-5 border border-dashed border-gray-200 rounded-lg">
                    ยังไม่มีประวัติ
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    {history.sessions.map((s) => (
                      <div
                        key={s.id}
                        className="flex items-center gap-3 px-3 py-2 rounded-lg border border-gray-100 text-xs"
                      >
                        <span
                          className={`w-2 h-2 rounded-full shrink-0 ${
                            s.online ? "bg-emerald-500" : "bg-gray-300"
                          }`}
                          title={s.online ? "ออนไลน์" : "ออกแล้ว"}
                        />
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-gray-900 truncate">
                            {s.subsystem_name || "—"}
                            <span className="text-gray-400 font-normal">
                              {" "}· {s.login_method || "—"}
                            </span>
                          </div>
                          <div className="text-gray-500 truncate">
                            {relTime(s.created_at)}
                            {s.ip && ` · ${s.ip}`}
                            {s.geo_country && ` · ${s.geo_country}`}
                            {s.browser && ` · ${s.browser}`}
                          </div>
                        </div>
                        {s.decision && (
                          <span
                            className={`text-[10px] px-1.5 py-0.5 rounded font-bold shrink-0 ${
                              s.decision.includes("block")
                                ? "bg-red-100 text-red-700"
                                : s.decision.includes("challenge") ||
                                    s.decision.includes("mfa")
                                  ? "bg-amber-100 text-amber-700"
                                  : s.decision.includes("warn")
                                    ? "bg-yellow-100 text-yellow-700"
                                    : "bg-emerald-100 text-emerald-700"
                            }`}
                          >
                            {s.decision}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
