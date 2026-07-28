"use client";

/**
 * SecurityCard — ตั้งค่า Always-2FA + factor ที่ต้องการใช้ก่อน (บัญชีของฉัน).
 *
 * Always-2FA = ขอยืนยัน factor ที่สอง (passkey/TOTP) ทุก login (ยุบเข้ากับ risk-based
 * gate เดียว — ไม่ซ้ำซ้อน). admin ถูกบังคับเปิด (toggle ล็อก).
 */

import { useCallback, useEffect, useState } from "react";
import {
  fetchSecurityStatus,
  updateSecurity,
  type SecurityStatus,
} from "@/lib/passkey";

export function SecurityCard() {
  const [st, setSt] = useState<SecurityStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setSt(await fetchSecurityStatus());
    } catch (e) {
      setErr(e instanceof Error ? e.message : "โหลดไม่สำเร็จ");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const patch = async (body: {
    mfa_always?: boolean;
    mfa_preferred_factor?: "passkey" | "totp";
  }) => {
    setBusy(true);
    setErr(null);
    try {
      setSt(await updateSecurity(body));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "บันทึกไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  };

  if (!st) return null;

  const adminForced = st.is_admin;
  const on = st.effective_mfa_always;

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
      <div>
        <h3 className="text-lg font-bold text-gray-900">การยืนยันตัวตนเมื่อเข้าสู่ระบบ</h3>
        <p className="mt-0.5 text-sm text-gray-500">
          ปกติระบบจะขอยืนยันซ้ำเฉพาะเมื่อตรวจพบความเสี่ยง — เปิดด้านล่างเพื่อขอทุกครั้ง
        </p>
      </div>

      {err && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {err}
        </div>
      )}

      {/* Always-2FA toggle */}
      <div className="flex items-center justify-between gap-4 rounded-lg border border-gray-100 bg-gray-50 p-4">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-gray-900">
            ขอยืนยันตัวตนทุกครั้งที่ล็อกอิน (Always-2FA)
          </div>
          <div className="mt-0.5 text-xs text-gray-500">
            {adminForced
              ? "บังคับสำหรับผู้ดูแลระบบ — ปิดไม่ได้"
              : "ยืนยันด้วย Passkey หรือ Authenticator หลังล็อกอิน Google ทุกครั้ง"}
          </div>
        </div>
        <button
          role="switch"
          aria-checked={on}
          disabled={busy || adminForced}
          onClick={() => patch({ mfa_always: !st.mfa_always })}
          className={`relative h-6 w-11 shrink-0 rounded-full transition ${
            on ? "bg-emerald-500" : "bg-gray-300"
          } ${adminForced ? "opacity-60 cursor-not-allowed" : ""}`}
        >
          <span
            className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition ${
              on ? "left-[22px]" : "left-0.5"
            }`}
          />
        </button>
      </div>

      {/* preferred factor — แสดงเมื่อมีทั้ง passkey + totp (มีตัวเลือกจริง) */}
      {st.has_passkey && st.has_totp && (
        <div className="rounded-lg border border-gray-100 p-4">
          <div className="text-sm font-semibold text-gray-900">
            วิธีที่ต้องการใช้ก่อน
          </div>
          <div className="mt-2 flex gap-2">
            {(["passkey", "totp"] as const).map((f) => (
              <button
                key={f}
                disabled={busy}
                onClick={() => patch({ mfa_preferred_factor: f })}
                className={`flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition ${
                  st.mfa_preferred_factor === f
                    ? "border-brand-500 bg-brand-50 text-brand-700"
                    : "border-gray-200 text-gray-600 hover:border-gray-300"
                }`}
              >
                {f === "passkey" ? "🔑 Passkey" : "📱 Authenticator"}
              </button>
            ))}
          </div>
        </div>
      )}

      {!st.has_second_factor && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          ยังไม่มี Passkey หรือ Authenticator — ตั้งค่าอย่างน้อย 1 อย่างด้านบนก่อนเปิด
          Always-2FA
        </div>
      )}
    </div>
  );
}
