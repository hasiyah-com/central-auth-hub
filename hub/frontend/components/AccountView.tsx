"use client";

/**
 * AccountView — บัญชีของฉัน (profile + Passkey / Backup codes).
 * ใช้ร่วมทั้ง admin (/account) และ developer (/developer/account) — เนื้อหาเดียวกัน
 * (profile จาก /api/me, passkey lifecycle). role ไหน login ก็เห็นของตัวเอง.
 */

import { useCallback, useEffect, useState } from "react";
import { Topbar } from "@/components/Topbar";
import {
  changeGoogleStart,
  fetchBackupCodesStatus,
  isPasskeySupported,
  isPlatformAuthenticatorAvailable,
  listPasskeys,
  regenerateBackupCodes,
  registerPasskey,
  type BackupCodesStatus,
  type PasskeyInfo,
} from "@/lib/passkey";
import { BackupCodesModal } from "@/components/account/BackupCodesModal";
import { PasskeyCard } from "@/components/account/PasskeyCard";
import { TotpCard } from "@/components/account/TotpCard";

type Me = {
  email: string;
  full_name: string | null;
  user_type: string | null;
  faculty: string | null;
  is_hub_admin: boolean;
};

export function AccountView() {
  const [me, setMe] = useState<Me | null>(null);

  const [supported, setSupported] = useState<boolean | null>(null);
  const [platformAvailable, setPlatformAvailable] = useState(false);
  const [passkeys, setPasskeys] = useState<PasskeyInfo[]>([]);
  const [maxPasskeys, setMaxPasskeys] = useState(10);
  const [backupStatus, setBackupStatus] = useState<BackupCodesStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [deviceName, setDeviceName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  // Change Google account (re-link) — passkey step-up → redirect ไป Google ใหม่
  const [googleBusy, setGoogleBusy] = useState(false);
  const [googleVerifying, setGoogleVerifying] = useState(false);
  const [googleErr, setGoogleErr] = useState<string | null>(null);

  const handleChangeGoogle = async () => {
    setGoogleErr(null);
    setGoogleBusy(true);
    try {
      const res = await changeGoogleStart(setGoogleVerifying);
      window.location.href = res.start_url; // redirect เริ่ม OAuth (page นำทางออก)
    } catch (e) {
      const detail = (e as { detail?: unknown })?.detail;
      const code =
        typeof detail === "object" && detail
          ? (detail as { code?: string }).code
          : undefined;
      if (code === "no_passkey") {
        setGoogleErr(
          "ต้องมี Passkey เพื่อเปลี่ยนบัญชี Google — ตั้งค่า Passkey ด้านล่างก่อน หรือใช้ Account Recovery"
        );
      } else if (e instanceof DOMException && e.name === "NotAllowedError") {
        setGoogleErr("ยกเลิกการยืนยัน Passkey — ลองอีกครั้ง");
      } else {
        setGoogleErr(
          typeof detail === "string" ? detail : "เริ่มเปลี่ยนบัญชีไม่สำเร็จ"
        );
      }
      setGoogleBusy(false);
    }
  };

  useEffect(() => {
    fetch("/api/me", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [list, bc] = await Promise.all([
        listPasskeys(),
        fetchBackupCodesStatus().catch(() => null),
      ]);
      setPasskeys(list.passkeys);
      setMaxPasskeys(list.max);
      setBackupStatus(bc);
    } catch (e) {
      setError(e instanceof Error ? e.message : "โหลดข้อมูลไม่สำเร็จ");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const ok = isPasskeySupported();
    setSupported(ok);
    if (ok) isPlatformAuthenticatorAvailable().then(setPlatformAvailable);
    refresh();
  }, [refresh]);

  const atMax = passkeys.length >= maxPasskeys;

  const handleRegister = async () => {
    if (!deviceName.trim()) {
      setError("กรุณาตั้งชื่ออุปกรณ์");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const res = await registerPasskey(deviceName.trim());
      if (res.backup_codes && res.backup_codes_must_acknowledge) {
        setBackupCodes(res.backup_codes);
      }
      setDeviceName("");
      setShowAdd(false);
      await refresh();
    } catch (e) {
      const message =
        e instanceof Error
          ? e.message
          : typeof e === "object" && e && "detail" in e
            ? typeof (e as { detail: unknown }).detail === "object"
              ? "ลงทะเบียนไม่สำเร็จ (อาจถึงจำนวนสูงสุด)"
              : String((e as { detail: unknown }).detail)
            : "ลงทะเบียน Passkey ไม่สำเร็จ";
      setError(message);
    } finally {
      setBusy(false);
    }
  };

  const initial = (me?.full_name || me?.email || "?").charAt(0).toUpperCase();

  return (
    <>
      <Topbar title="บัญชีของฉัน" />

      <div className="px-8 py-6 max-w-3xl space-y-6">
        {/* Profile card */}
        <div className="bg-white rounded-xl border border-ink-200 p-6 shadow-sm">
          <div className="flex items-center gap-4">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 grid place-items-center text-white text-2xl font-extrabold">
              {initial}
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h2 className="text-xl font-extrabold text-ink-900 truncate">
                  {me?.full_name || me?.email || "—"}
                </h2>
                {me?.is_hub_admin ? (
                  <span className="px-2 py-0.5 rounded bg-brand-50 text-brand-700 text-[11px] font-bold">
                    ADMIN
                  </span>
                ) : (
                  me?.user_type && (
                    <span className="px-2 py-0.5 rounded bg-violet-50 text-violet-700 text-[11px] font-bold">
                      {me.user_type.toUpperCase()}
                    </span>
                  )
                )}
              </div>
              <div className="text-sm text-ink-500 font-mono">{me?.email || ""}</div>
            </div>
          </div>

          <dl className="grid grid-cols-2 sm:grid-cols-3 gap-4 mt-5 pt-5 border-t border-ink-100">
            <Field label="ประเภทผู้ใช้" value={me?.user_type} />
            <Field label="คณะ / หน่วยงาน" value={me?.faculty} />
            <Field
              label="สิทธิ์"
              value={me?.is_hub_admin ? "ผู้ดูแลระบบ (Hub Admin)" : "นักพัฒนา (Developer)"}
            />
          </dl>
        </div>

        {/* Change Google account (re-link) */}
        <div className="bg-white rounded-xl border border-ink-200 p-6 shadow-sm">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="min-w-0">
              <h3 className="text-sm font-bold text-ink-800 flex items-center gap-2">
                <span>🔵</span> บัญชี Google ที่เชื่อม
              </h3>
              <p className="text-sm text-ink-500 mt-1">
                ใช้เข้าสู่ระบบ:{" "}
                <span className="font-mono text-ink-800">{me?.email || "—"}</span>
              </p>
              <p className="text-[11px] text-ink-400 mt-1 max-w-md leading-relaxed">
                เปลี่ยนได้ถ้าลืมรหัส Gmail / บัญชีถูกปิด / เปลี่ยนอีเมล — ข้อมูลและสิทธิ์
                เดิมอยู่ครบ (ต้องยืนยันด้วย Passkey ก่อน แล้วเลือกบัญชี Google ใหม่)
              </p>
            </div>
            <button
              onClick={handleChangeGoogle}
              disabled={googleBusy}
              className="px-4 py-2 rounded-lg border border-ink-300 hover:bg-ink-50 text-sm font-semibold text-ink-700 disabled:opacity-50 whitespace-nowrap"
            >
              {googleVerifying
                ? "กำลังยืนยัน…"
                : googleBusy
                  ? "กำลังเริ่ม…"
                  : "เปลี่ยนบัญชี Google"}
            </button>
          </div>
          {googleErr && (
            <div className="mt-3 text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-lg p-2.5">
              {googleErr}
              {googleErr.includes("Passkey") && (
                <>
                  {" · "}
                  <a href="/auth/passkey/recover" className="underline">
                    Account Recovery
                  </a>
                </>
              )}
            </div>
          )}
        </div>

        {/* Security heading */}
        <div className="flex items-center gap-2 pt-1">
          <span className="text-base">🔑</span>
          <h2 className="text-sm font-extrabold text-ink-800 uppercase tracking-wider">
            ความปลอดภัย · Passkey
          </h2>
        </div>

        {supported === false && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-900">
            <strong>เบราว์เซอร์นี้ไม่รองรับ Passkey.</strong> ใช้ Chrome, Edge,
            Safari, หรือ Firefox เวอร์ชั่นใหม่.
          </div>
        )}

        {/* Passkey list */}
        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-lg font-bold text-gray-900">Passkey ของคุณ</h3>
              <p className="text-sm text-gray-600 mt-0.5">
                {passkeys.length}/{maxPasskeys} อุปกรณ์
                {platformAvailable && " · ตรวจพบ biometric ในเครื่องนี้"}
              </p>
            </div>
            {supported && !atMax && !showAdd && (
              <button
                onClick={() => setShowAdd(true)}
                className="px-4 py-2 rounded-lg bg-emerald-600 text-white text-sm font-semibold hover:bg-emerald-700"
              >
                + เพิ่ม Passkey
              </button>
            )}
          </div>

          {loading ? (
            <div className="text-sm text-gray-400 py-6 text-center">กำลังโหลด…</div>
          ) : passkeys.length === 0 ? (
            <div className="text-sm text-gray-500 py-6 text-center border border-dashed border-gray-200 rounded-lg">
              ยังไม่มี Passkey — เพิ่มเพื่อ login แบบไม่ใช้รหัสผ่าน
            </div>
          ) : (
            <div className="space-y-2">
              {passkeys.map((pk) => (
                <PasskeyCard
                  key={pk.id}
                  pk={pk}
                  isLast={passkeys.length === 1}
                  onChanged={refresh}
                />
              ))}
            </div>
          )}

          {showAdd && (
            <div className="border-t border-gray-100 pt-4 space-y-3">
              <label className="text-sm font-medium text-gray-700">
                ชื่ออุปกรณ์ใหม่
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={deviceName}
                  onChange={(e) => setDeviceName(e.target.value)}
                  placeholder="MacBook Air, iPhone 15, YubiKey 5C"
                  disabled={busy}
                  maxLength={100}
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleRegister();
                  }}
                  className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500"
                />
                <button
                  onClick={handleRegister}
                  disabled={busy || !deviceName.trim()}
                  className={`px-4 py-2 rounded-lg font-semibold ${
                    busy || !deviceName.trim()
                      ? "bg-gray-200 text-gray-400 cursor-not-allowed"
                      : "bg-emerald-600 text-white hover:bg-emerald-700"
                  }`}
                >
                  {busy ? "กำลังลงทะเบียน…" : "ลงทะเบียน"}
                </button>
                <button
                  onClick={() => {
                    setShowAdd(false);
                    setDeviceName("");
                    setError(null);
                  }}
                  disabled={busy}
                  className="px-3 py-2 text-gray-500 hover:text-gray-700 text-sm"
                >
                  ยกเลิก
                </button>
              </div>
            </div>
          )}

          {atMax && (
            <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-2.5">
              ถึงจำนวนสูงสุด {maxPasskeys} อุปกรณ์ — ลบตัวเก่าก่อนเพิ่มใหม่
            </div>
          )}

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-800">
              {error}
            </div>
          )}
        </div>

        {/* Authenticator (TOTP) */}
        <TotpCard />

        {/* Backup codes status + regenerate */}
        {backupStatus && backupStatus.generation > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-bold text-gray-900 mb-1">Backup Codes</h3>
                <p className="text-sm text-gray-600">
                  เหลือ <strong>{backupStatus.remaining}</strong>/{backupStatus.total} codes
                  {backupStatus.low && (
                    <span className="text-amber-600"> · ⚠ ใกล้หมด — ควรสร้างใหม่</span>
                  )}
                </p>
              </div>
              <button
                onClick={async () => {
                  if (
                    !confirm("สร้าง backup codes ชุดใหม่? codes เก่าทั้งหมดจะใช้ไม่ได้")
                  )
                    return;
                  setBusy(true);
                  try {
                    const r = await regenerateBackupCodes();
                    setBackupCodes(r.backup_codes);
                    await refresh();
                  } catch (e) {
                    setError(e instanceof Error ? e.message : "สร้างใหม่ไม่สำเร็จ");
                  } finally {
                    setBusy(false);
                  }
                }}
                disabled={busy}
                className={`px-4 py-2 rounded-lg text-sm font-semibold ${
                  backupStatus.low
                    ? "bg-amber-600 text-white hover:bg-amber-700"
                    : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                }`}
              >
                🔄 สร้างใหม่
              </button>
            </div>
          </div>
        )}
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

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="text-[11px] font-semibold text-ink-400 uppercase tracking-wider">
        {label}
      </dt>
      <dd className="text-sm font-medium text-ink-800 mt-0.5">{value || "—"}</dd>
    </div>
  );
}
