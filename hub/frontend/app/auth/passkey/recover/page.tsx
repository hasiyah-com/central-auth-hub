"use client";

/**
 * Passkey recovery + regenerate (Phase 4 + lifecycle).
 *   - Backup Code → revoke passkey
 *   - Email OTP   → revoke passkey + codes ใหม่
 *   - ขอ codes ใหม่ → regenerate codes (ไม่แตะ passkey)
 * codes ใหม่ → CodesAck (copy/download/checkbox/ยืนยัน → login).
 *
 * return_to: ถ้ามาจาก subsystem flow → ?return_to=<url> ให้กลับไป login ของ subsystem
 *   เพื่อกัน open-redirect: รับเฉพาะ path relative ('/...') หรือ URL ที่ hostname
 *   ตรงกับ Hub origin (subsystem ใน dev อยู่บน localhost คนละ port → match แล้ว)
 */

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  recoverEmailOtpStart,
  recoverEmailOtpVerify,
  recoverWithBackupCode,
  recoverWithTotp,
  submitRecoveryRequest,
  regenOtpStart,
  regenOtpVerify,
} from "@/lib/passkey";
import { CodesAck } from "./_CodesAck";
import styles from "./recovery.module.css";

type Tab = "backup" | "otp" | "regen" | "totp" | "ticket";

const METHODS: Array<{ id: Tab; code: string; title: string; description: string }> = [
  { id: "backup", code: "BC", title: "Backup Code", description: "ใช้รหัสสำรองที่บันทึกไว้" },
  { id: "otp", code: "EM", title: "Email OTP", description: "รับรหัสยืนยันทางอีเมล" },
  { id: "totp", code: "AU", title: "Authenticator", description: "ยืนยันด้วยรหัสจากแอป" },
  { id: "ticket", code: "AD", title: "ขอความช่วยเหลือ", description: "ส่งคำขอให้ผู้ดูแลตรวจสอบ" },
  { id: "regen", code: "RC", title: "สร้าง Codes ใหม่", description: "เปลี่ยนเฉพาะชุดรหัสสำรอง" },
];

const HUB_URL = process.env.NEXT_PUBLIC_HUB_URL || "http://localhost:8000";

/** Allow return_to เฉพาะ relative path หรือ URL ที่ hostname เดียวกับ Hub
 *  (ครอบคลุม subsystem ใน dev: localhost:8001/8002 — hostname=localhost เหมือนกัน) */
function safeReturnTo(raw: string | null): string {
  if (!raw) return "/auth/login";
  if (raw.startsWith("/") && !raw.startsWith("//")) return raw;
  try {
    const url = new URL(raw);
    const hubHost = new URL(HUB_URL).hostname;
    if ((url.protocol === "http:" || url.protocol === "https:") && url.hostname === hubHost) {
      return url.toString();
    }
  } catch {
    // ignore — fallthrough
  }
  return "/auth/login";
}

function errMsg(e: unknown): string {
  if (typeof e === "object" && e && "detail" in e) {
    const d = (e as { detail: unknown }).detail;
    if (typeof d === "object" && d && "message" in d)
      return String((d as { message: unknown }).message);
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return "รูปแบบอีเมลไม่ถูกต้อง";
  }
  return e instanceof Error ? e.message : "ไม่สำเร็จ";
}

function RecoverInner() {
  const params = useSearchParams();
  const returnTo = safeReturnTo(params.get("return_to"));
  const isExternal = returnTo !== "/auth/login";

  const [tab, setTab] = useState<Tab>("backup");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [otp, setOtp] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [doneMsg, setDoneMsg] = useState<string | null>(null);
  const [newCodes, setNewCodes] = useState<string[] | null>(null);

  const reset = () => {
    setError(null);
    setInfo(null);
    setOtp("");
    setOtpSent(false);
  };

  const goLogin = () => {
    window.location.href = returnTo;
  };

  const doBackup = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await recoverWithBackupCode(email, code);
      setDoneMsg(r.message);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const sendOtp = async (regen: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const r = regen
        ? await regenOtpStart(email)
        : await recoverEmailOtpStart(email);
      setOtpSent(true);
      setInfo(r.message);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const doTotp = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await recoverWithTotp(email, code);
      window.location.href = r.start_url; // → เริ่ม OAuth เชื่อม Gmail ใหม่
    } catch (e) {
      setError(errMsg(e));
      setBusy(false);
    }
  };

  const doTicket = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await submitRecoveryRequest({ email, reason });
      setDoneMsg(r.message);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const verifyOtp = async (regen: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const r = regen
        ? await regenOtpVerify(email, otp)
        : await recoverEmailOtpVerify(email, otp);
      if (r.backup_codes && r.backup_codes.length) setNewCodes(r.backup_codes);
      else setDoneMsg(r.message);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const activeMethod = METHODS.find((method) => method.id === tab) ?? METHODS[0];
  const methodButton = (method: (typeof METHODS)[number]) => (
    <button
      key={method.id}
      type="button"
      role="tab"
      aria-selected={tab === method.id}
      className={tab === method.id ? styles.methodActive : styles.method}
      onClick={() => { setTab(method.id); reset(); }}
    >
      <span>{method.code}</span>
      <div><strong>{method.title}</strong><small>{method.description}</small></div>
    </button>
  );

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <a href="/auth/login" className={styles.brand} aria-label="Central Auth Hub">
          <span>H</span><div><strong>Central Auth Hub</strong><small>IDENTITY CONTROL</small></div>
        </a>
        <div className={styles.secureStatus}><i /> SECURE RECOVERY SESSION</div>
      </header>

      <div className={styles.shell}>
        <aside className={styles.context}>
          <div>
            <span className={styles.eyebrow}>ACCOUNT RECOVERY</span>
            <h1>กลับเข้าใช้งานบัญชี<br />อย่างปลอดภัย</h1>
            <p>เลือกวิธียืนยันตัวตนที่คุณยังเข้าถึงได้ ระบบจะยกเลิก Passkey เดิมก่อนให้ตั้งค่าอุปกรณ์ใหม่</p>
          </div>
          <ol className={styles.steps}>
            <li className={styles.stepActive}><span>01</span><div><strong>เลือกวิธียืนยัน</strong><small>ใช้ข้อมูลที่คุณยังเข้าถึงได้</small></div></li>
            <li><span>02</span><div><strong>ตรวจสอบตัวตน</strong><small>ยืนยันรหัสหรือส่งคำขอ</small></div></li>
            <li><span>03</span><div><strong>กลับเข้าสู่ระบบ</strong><small>ตั้ง Passkey ใหม่หลัง Login</small></div></li>
          </ol>
          <div className={styles.securityNote}><span>i</span><p><strong>ไม่มีรหัสผ่านถูกจัดเก็บในหน้านี้</strong>รหัสยืนยันมีอายุจำกัดและใช้ได้เพียงครั้งเดียว</p></div>
        </aside>

        <section className={styles.workspace} aria-labelledby="recovery-title">
          <header className={styles.workspaceHeader}>
            <div><span className={styles.eyebrow}>PASSKEY / RECOVERY</span><h2 id="recovery-title">{tab === "regen" ? "สร้าง Backup Codes ชุดใหม่" : "กู้การเข้าถึงบัญชี"}</h2></div>
            <span className={styles.sessionId}>SESSION · ACTIVE</span>
          </header>

          {newCodes ? (
            <div className={styles.resultPanel}><CodesAck codes={newCodes} onConfirm={goLogin} note={tab === "regen" ? "Backup codes ชุดใหม่ — Passkey ของคุณยังใช้ได้" : "Passkey เดิมถูกยกเลิกแล้ว กรุณาบันทึก Backup codes ชุดใหม่"} /></div>
          ) : doneMsg ? (
            <div className={styles.donePanel}>
              <span className={styles.eyebrow}>RECOVERY COMPLETE</span><h3>ดำเนินการสำเร็จ</h3><p>{doneMsg}</p>
              <button type="button" onClick={goLogin}>{isExternal ? "กลับไปหน้า Login ของระบบย่อย" : "ไปหน้า Login"}<span>→</span></button>
            </div>
          ) : (
            <div className={styles.recoveryGrid}>
              <nav className={styles.methods} role="tablist" aria-label="วิธีกู้บัญชี">{METHODS.map(methodButton)}</nav>

              <section className={styles.formPanel} role="tabpanel">
                <div className={styles.methodHeading}><span>{activeMethod.code}</span><div><h3>{activeMethod.title}</h3><p>{activeMethod.description}</p></div></div>

                {(tab === "totp" || tab === "ticket" || tab === "regen") && (
                  <div className={styles.guidance}>
                    {tab === "totp" && "ใช้วิธีนี้เมื่อเข้า Gmail และ Passkey เดิมไม่ได้ แต่ยังมีแอป Authenticator"}
                    {tab === "ticket" && "หากไม่เหลือวิธียืนยัน ผู้ดูแลจะตรวจสอบข้อมูลก่อนออกลิงก์กู้บัญชี"}
                    {tab === "regen" && "ระบบจะสร้าง Backup codes ชุดใหม่ โดยไม่ยกเลิก Passkey ที่ใช้งานอยู่"}
                  </div>
                )}

                <label className={styles.field}>
                  <span>อีเมลบัญชีมหาวิทยาลัย</span>
                  <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@uni.ac.th" autoComplete="email" disabled={busy} />
                </label>

                {tab === "backup" ? <>
                  <label className={styles.field}><span>Backup Code</span><input type="text" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="AB3D-7K9P" disabled={busy} maxLength={20} className={styles.codeInput} /></label>
                  <button type="button" className={styles.primaryButton} onClick={doBackup} disabled={busy || !email.trim() || !code.trim()}>{busy ? "กำลังตรวจสอบ…" : "ตรวจสอบและกู้บัญชี"}<span>→</span></button>
                </> : tab === "totp" ? <>
                  <label className={styles.field}><span>รหัสจาก Authenticator</span><input type="text" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="000 000" inputMode="numeric" autoComplete="one-time-code" disabled={busy} className={styles.otpInput} /></label>
                  <button type="button" className={styles.primaryButton} onClick={doTotp} disabled={busy || !email.trim() || code.length !== 6}>{busy ? "กำลังตรวจสอบ…" : "ยืนยันและเปลี่ยนบัญชี Google"}<span>→</span></button>
                </> : tab === "ticket" ? <>
                  <label className={styles.field}><span>รายละเอียดเพิ่มเติม <small>ไม่บังคับ</small></span><textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="อธิบายสั้น ๆ ว่าไม่สามารถเข้าใช้งานได้เพราะอะไร" disabled={busy} rows={4} /></label>
                  <button type="button" className={styles.primaryButton} onClick={doTicket} disabled={busy || !email.trim()}>{busy ? "กำลังส่งคำขอ…" : "ส่งคำขอให้ผู้ดูแล"}<span>→</span></button>
                </> : !otpSent ? (
                  <button type="button" className={styles.primaryButton} onClick={() => sendOtp(tab === "regen")} disabled={busy || !email.trim()}>{busy ? "กำลังส่ง…" : "ส่ง OTP ทางอีเมล"}<span>→</span></button>
                ) : <>
                  <label className={styles.field}><span>รหัส OTP 6 หลัก</span><input type="text" value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="000 000" disabled={busy} maxLength={6} inputMode="numeric" autoComplete="one-time-code" className={styles.otpInput} /></label>
                  <button type="button" className={styles.primaryButton} onClick={() => verifyOtp(tab === "regen")} disabled={busy || otp.length !== 6}>{busy ? "กำลังตรวจสอบ…" : "ยืนยันรหัส OTP"}<span>→</span></button>
                </>}

                {info && <div className={styles.infoMessage} role="status"><span>i</span>{info}</div>}
                {error && <div className={styles.errorMessage} role="alert"><span>!</span>{error}</div>}
                <a href={returnTo} className={styles.backLink}>← {isExternal ? "กลับหน้า Login ของระบบย่อย" : "กลับหน้า Login"}</a>
              </section>
            </div>
          )}
        </section>
      </div>

      <footer className={styles.footer}><span>Central Auth Hub</span><span>TLS 1.3 · WEBAUTHN · OAUTH 2.0</span><span>Princess of Naradhiwas University</span></footer>
    </main>
  );
}

export default function RecoverPage() {
  return (
    <Suspense fallback={null}>
      <RecoverInner />
    </Suspense>
  );
}
