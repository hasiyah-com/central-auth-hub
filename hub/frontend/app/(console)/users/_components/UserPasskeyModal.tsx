"use client";

/**
 * Admin passkey overview modal — read-only list ของ user คนหนึ่ง + reset.
 */

import { useEffect, useState } from "react";
import {
  adminListUserPasskeys,
  adminResetUserPasskeys,
  type AdminUserPasskeys,
} from "@/lib/passkey";

function relTime(iso: string | null): string {
  if (!iso) return "ยังไม่เคยใช้";
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

export function UserPasskeyModal({ userId, userName, onClose }: Props) {
  const [data, setData] = useState<AdminUserPasskeys | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [verifying, setVerifying] = useState(false);

  const load = () => {
    setLoading(true);
    adminListUserPasskeys(userId)
      .then(setData)
      .catch((e) => setError(e?.detail || "โหลดไม่สำเร็จ"))
      .finally(() => setLoading(false));
  };

  useEffect(load, [userId]);

  const reset = async () => {
    if (!confirm(`Reset passkey ทั้งหมดของ ${userName}? user ต้องตั้งค่าใหม่`))
      return;
    setResetting(true);
    try {
      const r = await adminResetUserPasskeys(userId, setVerifying);
      alert(r.message);
      load();
    } catch (e) {
      setError(
        typeof e === "object" && e && "detail" in e
          ? String((e as { detail: unknown }).detail)
          : "reset ไม่สำเร็จ"
      );
    } finally {
      setResetting(false);
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
      <div className="bg-white rounded-xl shadow-2xl max-w-lg w-full max-h-[90vh] overflow-y-auto">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-gray-900">Passkey ของผู้ใช้</h2>
            <p className="text-xs text-gray-500 font-mono">{userName}</p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700 text-xl"
          >
            ✕
          </button>
        </div>

        <div className="px-6 py-5 space-y-3">
          {loading ? (
            <div className="text-sm text-gray-400 text-center py-6">กำลังโหลด…</div>
          ) : error ? (
            <div className="text-sm text-red-600">{error}</div>
          ) : data && data.passkeys.length === 0 ? (
            <div className="text-sm text-gray-500 text-center py-6 border border-dashed border-gray-200 rounded-lg">
              user นี้ยังไม่มี Passkey
            </div>
          ) : (
            data?.passkeys.map((pk) => (
              <div
                key={pk.id}
                className="flex items-center gap-3 px-3 py-2.5 rounded-lg border border-gray-200"
              >
                <span className="text-lg">
                  {pk.device_type === "platform" ? "💻" : "🔑"}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-gray-900 truncate">
                    {pk.device_name}
                  </div>
                  <div className="text-xs text-gray-500">
                    ใช้ล่าสุด {relTime(pk.last_used_at)}
                    {pk.last_used_country ? ` · ${pk.last_used_country}` : ""}
                    {pk.counter_regression_count > 0 && (
                      <span className="text-amber-600">
                        {" "}· ⚠ {pk.counter_regression_count}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}

          {data && (
            <div className="text-xs text-gray-500 pt-1">
              Backup codes เหลือ {data.backup_codes.remaining}/
              {data.backup_codes.total}
              {data.backup_codes.low && (
                <span className="text-amber-600"> · ใกล้หมด</span>
              )}
            </div>
          )}
        </div>

        {data && data.passkeys.length > 0 && (
          <div className="px-6 py-4 bg-gray-50 border-t border-gray-200 flex justify-end">
            <button
              onClick={reset}
              disabled={resetting}
              className="px-4 py-2 rounded-lg bg-red-600 text-white text-sm font-semibold hover:bg-red-700 disabled:opacity-50"
            >
              {resetting ? "กำลัง reset…" : "🗑️ Reset Passkeys ทั้งหมด"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
