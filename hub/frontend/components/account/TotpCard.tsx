"use client";

/**
 * TotpCard — จัดการ Authenticator (TOTP) ในหน้าบัญชี.
 * enroll: step-up → โชว์ QR (qrcode.react) + secret → ใส่รหัส 6 หลัก → ACTIVE.
 * ปิด/สถานะ. ใช้เป็น Fallback Authentication Factor สำหรับกู้บัญชี.
 *
 * สไตล์ cx-* (signal-console.css) — ต้องอยู่ใต้ `.sc` ซึ่ง AccountView ครอบให้
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
  const [enroll, setEnroll] = useState<{ uri: string; secret: string } | null>(
    null
  );
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
      const c =
        typeof d === "object" && d ? (d as { code?: string }).code : undefined;
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

  const chipClass = enabled
    ? "cx-chip signal"
    : status === "SUSPENDED"
      ? "cx-chip warn"
      : "cx-chip";

  return (
    <article className="cx-panel">
      {verifying && (
        <div className="cx-verify-overlay">
          <div>กำลังยืนยันตัวตน — ทำตามที่อุปกรณ์แจ้ง</div>
        </div>
      )}

      <header>
        <div>
          <span className="mono">authenticator app</span>
          <h2>Authenticator (TOTP)</h2>
        </div>
        {!loading && (
          <span className={chipClass}>
            {enabled
              ? "เปิดใช้งาน"
              : status === "SUSPENDED"
                ? "ระงับ"
                : "ยังไม่เปิด"}
          </span>
        )}
      </header>

      <div className="cx-setting-row">
        <div>
          <b>แอปยืนยันตัวตน (Google / Microsoft Authenticator)</b>
          <small>
            ใช้กู้บัญชีเมื่อเข้า email หรือ Passkey ไม่ได้ — รหัส 6 หลักเปลี่ยนทุก 30
            วินาที
          </small>
        </div>
      </div>

      {error && <div className="cx-inline-error">{error}</div>}

      {enroll ? (
        <div className="cx-totp-enroll">
          <p className="cx-totp-step">
            1. สแกน QR ด้วยแอป Authenticator (หรือกรอก secret เอง)
          </p>
          <div className="cx-totp-qr">
            <div>
              <QRCodeCanvas value={enroll.uri} size={150} />
            </div>
            <div className="cx-totp-secret">
              <small>secret (กรอกเองถ้าสแกนไม่ได้)</small>
              <code>{enroll.secret}</code>
            </div>
          </div>

          <p className="cx-totp-step">2. ใส่รหัส 6 หลักที่แอปแสดง</p>
          <div className="cx-totp-code">
            <input
              value={code}
              onChange={(e) =>
                setCode(e.target.value.replace(/\D/g, "").slice(0, 6))
              }
              placeholder="000000"
              inputMode="numeric"
              autoFocus
              aria-label="รหัส 6 หลัก"
            />
            <button
              type="button"
              className="cx-primary"
              onClick={confirm}
              disabled={busy || code.length !== 6}
            >
              {busy ? "กำลังยืนยัน" : "ยืนยัน"}
            </button>
            <button
              type="button"
              onClick={() => {
                setEnroll(null);
                setCode("");
                setError(null);
              }}
              disabled={busy}
            >
              ยกเลิก
            </button>
          </div>
        </div>
      ) : loading ? (
        <div className="cx-empty sm">
          <strong>กำลังโหลด</strong>
        </div>
      ) : (
        <div className="cx-panel-foot">
          {enabled || status === "SUSPENDED" ? (
            <button
              type="button"
              className="cx-panel-action danger"
              onClick={disable}
              disabled={busy}
            >
              ปิด / ลบ Authenticator
            </button>
          ) : (
            <button
              type="button"
              className="cx-panel-action cx-primary"
              onClick={startEnroll}
              disabled={busy}
            >
              {busy ? "กำลังเริ่ม" : "เปิดใช้งาน Authenticator"}
            </button>
          )}
        </div>
      )}
    </article>
  );
}
