"use client";

/**
 * Account Security — Phase 1 minimal Add Passkey UI (plan v3).
 *
 * Phase 3 will extend this with: list, rename, delete, last_used,
 * backup-codes status panel, regenerate flow.
 */

import { useEffect, useState } from "react";
import { Topbar } from "@/components/Topbar";
import {
  isPasskeySupported,
  isPlatformAuthenticatorAvailable,
  registerPasskey,
  type RegisterFinishResult,
} from "@/lib/passkey";
import { BackupCodesModal } from "./_components/BackupCodesModal";

export default function SecurityPage() {
  const [supported, setSupported] = useState<boolean | null>(null);
  const [platformAvailable, setPlatformAvailable] = useState(false);
  const [deviceName, setDeviceName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RegisterFinishResult | null>(null);
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);

  useEffect(() => {
    const ok = isPasskeySupported();
    setSupported(ok);
    if (ok) isPlatformAuthenticatorAvailable().then(setPlatformAvailable);
  }, []);

  const handleRegister = async () => {
    if (!deviceName.trim()) {
      setError("กรุณาตั้งชื่ออุปกรณ์");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const res = await registerPasskey(deviceName.trim());
      setResult(res);
      if (res.backup_codes && res.backup_codes_must_acknowledge) {
        setBackupCodes(res.backup_codes);
      }
      setDeviceName("");
    } catch (e) {
      const message =
        e instanceof Error
          ? e.message
          : typeof e === "object" && e && "detail" in e
            ? String((e as { detail: unknown }).detail)
            : "ลงทะเบียน Passkey ไม่สำเร็จ";
      setError(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Topbar title="ความปลอดภัยของบัญชี" />

      <div className="px-8 py-6 max-w-3xl space-y-6">
        {/* Feature support banner */}
        {supported === false && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-900">
            <strong>เบราว์เซอร์นี้ไม่รองรับ Passkey.</strong> กรุณาใช้ Chrome,
            Edge, Safari, หรือ Firefox เวอร์ชั่นใหม่.
          </div>
        )}

        {supported && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-sm text-blue-900">
            <div className="font-semibold mb-1">
              ✅ เบราว์เซอร์รองรับ Passkey
            </div>
            {platformAvailable ? (
              <div>
                ตรวจพบ TouchID / Windows Hello / Biometric — ใช้ลงทะเบียนได้เลย.
              </div>
            ) : (
              <div>
                ไม่พบ platform authenticator — ใช้ YubiKey หรือมือถือ (Mobile-as-key)
                ได้.
              </div>
            )}
          </div>
        )}

        {/* Add Passkey form */}
        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
          <div>
            <h2 className="text-lg font-bold text-gray-900">เพิ่ม Passkey</h2>
            <p className="text-sm text-gray-600 mt-1">
              ลงทะเบียนอุปกรณ์ใหม่ (TouchID, Windows Hello, YubiKey, มือถือ).
              Passkey แรกจะสร้าง backup codes 10 ตัวให้บันทึกเก็บไว้.
            </p>
          </div>

          <div className="space-y-2">
            <label htmlFor="deviceName" className="text-sm font-medium text-gray-700">
              ชื่ออุปกรณ์
            </label>
            <input
              id="deviceName"
              type="text"
              value={deviceName}
              onChange={(e) => setDeviceName(e.target.value)}
              placeholder="MacBook Air, iPhone 15, YubiKey 5C"
              disabled={!supported || busy}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 disabled:bg-gray-100"
              maxLength={100}
            />
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-800">
              {error}
            </div>
          )}

          {result && !backupCodes && (
            <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-3 text-sm text-emerald-800">
              ✓ ลงทะเบียน <strong>{result.device_name}</strong> สำเร็จ (
              {result.device_type})
            </div>
          )}

          <button
            onClick={handleRegister}
            disabled={!supported || busy || !deviceName.trim()}
            className={`w-full py-2.5 rounded-lg font-semibold transition ${
              !supported || busy || !deviceName.trim()
                ? "bg-gray-200 text-gray-400 cursor-not-allowed"
                : "bg-emerald-600 text-white hover:bg-emerald-700"
            }`}
          >
            {busy ? "กำลังลงทะเบียน…" : "🔑 ลงทะเบียน Passkey"}
          </button>
        </div>
      </div>

      {backupCodes && (
        <BackupCodesModal
          codes={backupCodes}
          onAcknowledged={() => setBackupCodes(null)}
        />
      )}
    </>
  );
}
