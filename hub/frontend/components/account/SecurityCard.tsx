"use client";

/**
 * SecurityCard — ตั้งค่า Always-2FA + factor ที่ต้องการใช้ก่อน (บัญชีของฉัน).
 *
 * Always-2FA = ขอยืนยัน factor ที่สอง (passkey/TOTP) ทุก login (ยุบเข้ากับ risk-based
 * gate เดียว — ไม่ซ้ำซ้อน). admin ถูกบังคับเปิด (toggle ล็อก).
 *
 * สไตล์ cx-* (signal-console.css) — ต้องอยู่ใต้ `.sc` ซึ่ง AccountView ครอบให้
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
    <article className="cx-panel">
      <header>
        <div>
          <span className="mono">login policy</span>
          <h2>การยืนยันตัวตนเมื่อเข้าสู่ระบบ</h2>
        </div>
        <span className={on ? "cx-chip signal" : "cx-chip"}>
          {on ? "ทุกครั้ง" : "ตามความเสี่ยง"}
        </span>
      </header>

      {err && <div className="cx-inline-error">{err}</div>}

      <div className="cx-setting-row">
        <div>
          <b>ขอยืนยันตัวตนทุกครั้งที่ล็อกอิน (Always-2FA)</b>
          <small>
            {adminForced
              ? "บังคับสำหรับผู้ดูแลระบบ — ปิดไม่ได้"
              : "ปกติระบบขอยืนยันซ้ำเฉพาะเมื่อตรวจพบความเสี่ยง เปิดเพื่อขอทุกครั้งด้วย Passkey หรือ Authenticator"}
          </small>
        </div>
        <button
          type="button"
          role="switch"
          className="cx-switch"
          aria-checked={on}
          aria-label="ขอยืนยันตัวตนทุกครั้งที่ล็อกอิน"
          disabled={busy || adminForced}
          onClick={() => patch({ mfa_always: !st.mfa_always })}
        >
          <i />
        </button>
      </div>

      {/* ปัจจัยที่ใช้ก่อน — แสดงเมื่อมีทั้ง passkey + totp (มีตัวเลือกจริง) */}
      {st.has_passkey && st.has_totp && (
        <div className="cx-setting-row">
          <div style={{ width: "100%" }}>
            <b>วิธีที่ต้องการใช้ก่อน</b>
            <div className="cx-factor-pick">
              {(["passkey", "totp"] as const).map((f) => (
                <button
                  key={f}
                  type="button"
                  disabled={busy}
                  className={st.mfa_preferred_factor === f ? "on" : undefined}
                  onClick={() => patch({ mfa_preferred_factor: f })}
                >
                  {f === "passkey" ? "Passkey" : "Authenticator"}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {!st.has_second_factor && (
        <div className="cx-inline-warn">
          ยังไม่มี Passkey หรือ Authenticator — ตั้งค่าอย่างน้อย 1 อย่างด้านบนก่อนเปิด
          Always-2FA
        </div>
      )}
    </article>
  );
}
