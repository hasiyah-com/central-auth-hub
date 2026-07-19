"use client";

/**
 * TotpCard — จัดการ Authenticator (TOTP) ในหน้าบัญชี.
 * enroll: step-up → โชว์ QR (qrcode.react) + secret → ใส่รหัส 6 หลัก → ACTIVE.
 * ปิด/สถานะ. ใช้เป็น Fallback Authentication Factor สำหรับกู้บัญชี.
 */

import { useEffect, useState } from "react";
import { QRCodeCanvas } from "qrcode.react";
import {
  totpStatus,
  totpEnrollStart,
  totpEnrollVerify,
  totpDisable,
} from "@/lib/passkey";

export function TotpCard() {
  const [status, setStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [verifying, setVerifying] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // enroll wizard
  const [enroll, setEnroll] = useState<{ uri: string; secret: string } | null>(null);
  const [code, setCode] = useState("");

  const refresh = () =>
    totpStatus()
      .then((s) => setStatus(s.status))
      .catch(() => setStatus(null))
      .finally(() => setLoading(false));

  useEffect(() => {
    refresh();
  }, []);

  const enabled = status === "ACTIVE";

  const startEnroll = async () => {
    setError(null);
    setBusy(true);
    try {
      const r = await totpEnrollStart(setVerifying);
      setEnroll({ uri: r.otpauth_uri, secret: r.secret });
    } catch (e) {
      const d = (e as { detail?: unknown })?.detail;
      const c = typeof d === "object" && d ? (d as { code?: string }).code : undefined;
      if (c === "no_passkey")
        setError("ต้องมี Passkey หรือยืนยันตัวตนก่อนเปิด Authenticator");
      else if (e instanceof DOMException && e.name === "NotAllowedError")
        setError("ยกเลิกการยืนยัน — ลองอีกครั้ง");
      else setError(typeof d === "string" ? d : "เริ่มไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    setError(null);
    setBusy(true);
    try {
      await totpEnrollVerify(code);
      setEnroll(null);
      setCode("");
      await refresh();
    } catch (e) {
      const d = (e as { detail?: unknown })?.detail;
      setError(
        typeof d === "object" && d
          ? (d as { message?: string }).message || "รหัสไม่ถูกต้อง"
          : "รหัสไม่ถูกต้อง"
      );
    } finally {
      setBusy(false);
    }
  };

  const disable = async () => {
    if (!window.confirm("ปิด Authenticator? จะใช้กู้บัญชีด้วยวิธีนี้ไม่ได้")) return;
    setBusy(true);
    setError(null);
    try {
      await totpDisable(setVerifying);
      await refresh();
    } catch (e) {
      setError((e as { detail?: string })?.detail || "ปิดไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
      {verifying && (
        <div className="fixed inset-0 z-[60] grid place-items-center bg-black/40">
          <div className="bg-white rounded-2xl px-6 py-5 shadow-xl text-sm text-ink-700">
            🔐 กำลังยืนยันตัวตน… ทำตามที่อุปกรณ์แจ้ง
          </div>
        </div>
      )}

      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-bold text-gray-900 flex items-center gap-2">
            🔐 Authenticator (TOTP)
          </h3>
          <p className="text-sm text-gray-600 mt-0.5">
            แอปยืนยันตัวตน (Google/Microsoft Authenticator) — ใช้กู้บัญชีเมื่อเข้า email/Passkey ไม่ได้
          </p>
        </div>
        {!loading && (
          <span
            className={
              "text-[11px] font-bold px-2 py-1 rounded-full " +
              (enabled
                ? "bg-emerald-100 text-emerald-800"
                : status === "SUSPENDED"
                  ? "bg-amber-100 text-amber-800"
                  : "bg-ink-100 text-ink-500")
            }
          >
            {enabled ? "เปิดใช้งาน" : status === "SUSPENDED" ? "ระงับ" : "ยังไม่เปิด"}
          </span>
        )}
      </div>

      {error && (
        <div className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-lg p-2.5">
          {error}
        </div>
      )}

      {/* Enroll wizard */}
      {enroll ? (
        <div className="border-t border-gray-100 pt-4 space-y-3">
          <p className="text-sm text-gray-700">
            1. สแกน QR ด้วยแอป Authenticator (หรือกรอก secret เอง)
          </p>
          <div className="flex items-center gap-4 flex-wrap">
            <div className="bg-white p-2 rounded-lg border border-ink-200">
              <QRCodeCanvas value={enroll.uri} size={160} />
            </div>
            <div className="text-xs">
              <div className="text-ink-400 mb-1">Secret (กรอกเองถ้าสแกนไม่ได้)</div>
              <code className="font-mono bg-ink-50 px-2 py-1 rounded break-all">
                {enroll.secret}
              </code>
            </div>
          </div>
          <p className="text-sm text-gray-700">2. ใส่รหัส 6 หลักที่แอปแสดง</p>
          <div className="flex gap-2">
            <input
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              placeholder="000000"
              inputMode="numeric"
              autoFocus
              className="w-32 px-3 py-2 border border-gray-300 rounded-lg font-mono tracking-widest text-center focus:ring-2 focus:ring-emerald-500"
            />
            <button
              onClick={confirm}
              disabled={busy || code.length !== 6}
              className="px-4 py-2 rounded-lg bg-emerald-600 text-white text-sm font-semibold hover:bg-emerald-700 disabled:opacity-40"
            >
              {busy ? "กำลังยืนยัน…" : "ยืนยัน"}
            </button>
            <button
              onClick={() => {
                setEnroll(null);
                setCode("");
                setError(null);
              }}
              disabled={busy}
              className="px-3 py-2 text-gray-500 hover:text-gray-700 text-sm"
            >
              ยกเลิก
            </button>
          </div>
        </div>
      ) : loading ? (
        <div className="text-sm text-gray-400">กำลังโหลด…</div>
      ) : enabled || status === "SUSPENDED" ? (
        <div className="flex items-center gap-2">
          <button
            onClick={disable}
            disabled={busy}
            className="px-4 py-2 rounded-lg border border-rose-200 text-rose-700 text-sm font-semibold hover:bg-rose-50 disabled:opacity-50"
          >
            ปิด / ลบ Authenticator
          </button>
        </div>
      ) : (
        <button
          onClick={startEnroll}
          disabled={busy}
          className="px-4 py-2 rounded-lg bg-emerald-600 text-white text-sm font-semibold hover:bg-emerald-700 disabled:opacity-50"
        >
          {busy ? "กำลังเริ่ม…" : "+ เปิดใช้งาน Authenticator"}
        </button>
      )}
    </div>
  );
}
