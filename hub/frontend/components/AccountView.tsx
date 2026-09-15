"use client";

/**
 * AccountView — บัญชีของฉัน (profile + Passkey / TOTP / Backup codes).
 * ใช้ร่วมทั้ง admin (/account) และ developer (/developer/account) — เนื้อหาเดียวกัน
 * role ไหน login ก็เห็นของตัวเอง.
 *
 * โครงหน้า/สไตล์ port จากดีไซน์ Signal Console (cx-account-* ใน signal-console.css)
 *
 * ที่มาข้อมูล — ใช้ `/auth/me` ผ่าน /api/proxy ไม่ใช่ `/api/me`:
 *   `/api/me` เป็น Next route ที่ decode JWT จาก cookie ตรง ๆ ไม่มี refresh fallback
 *   พอ access token (15 นาที) หมดอายุจะได้ null -> ขึ้น "—" ทั้งหน้า ทั้งที่ passkey
 *   ยังโหลดได้ (proxy refresh ให้) `/auth/me` ผ่าน proxy จึงทั้งสด (อ่าน DB จริง
 *   ไม่ใช่ claim ใน token) และทนโทเคนหมดอายุ
 *
 * บล็อกที่ดีไซน์มีแต่ตัดออก (ไม่มีข้อมูลจริงรองรับ — ไม่ใส่ค่าสมมติ):
 *   RECENT SESSION / ACCOUNT STATUS / LAST SIGN-IN — ไม่มี endpoint ให้ user
 *   ดูข้อมูลของตัวเอง (มีแต่ฝั่ง admin) facts strip จึงใช้ ROLE / PASSKEY /
 *   รหัสสำรอง ซึ่งเป็นข้อมูลจริงทั้งหมด
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";
import {
  changeGoogleStart,
  fetchBackupCodesStatus,
  isPasskeySupported,
  isPlatformAuthenticatorAvailable,
  listPasskeys,
  regenerateBackupCodes,
  registerPasskey,
  totpStatus,
  type BackupCodesStatus,
  type PasskeyInfo,
  type TotpStatus,
} from "@/lib/passkey";
import { BackupCodesModal } from "@/components/account/BackupCodesModal";
import { PasskeyCard } from "@/components/account/PasskeyCard";
import { TotpCard } from "@/components/account/TotpCard";
import { SecurityCard } from "@/components/account/SecurityCard";
import "@/app/signal-room.css";
import "@/app/signal-console.css";

/** /auth/me — ข้อมูลสดจาก DB (ต่างจาก /api/me ที่อ่าน claim ใน JWT) */
type Me = {
  id: string;
  email: string;
  full_name: string | null;
  user_type: string | null;
  faculty: string | null;
  is_hub_admin: boolean;
};

/* ── ไอคอนเส้น — โปรเจกต์ไม่ได้ติดตั้ง lucide จึงวาดเป็น inline SVG ─────── */

function Icon({ children, size = 16 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

const IconMail = () => (
  <Icon size={13}>
    <rect x="2" y="4" width="20" height="16" rx="2" />
    <path d="m22 7-10 6L2 7" />
  </Icon>
);
const IconFingerprint = ({ size = 16 }: { size?: number }) => (
  <Icon size={size}>
    <path d="M12 10a2 2 0 0 0-2 2c0 1.02-.1 2.51-.26 4" />
    <path d="M14 13.12c0 2.38 0 6.38-1 8.88" />
    <path d="M17.29 21.02c.12-.6.43-2.3.5-3.02" />
    <path d="M2 12a10 10 0 0 1 18-6" />
    <path d="M2 16h.01" />
    <path d="M21.8 16c.2-2 .13-5.35 0-6" />
    <path d="M5 19.5C5.5 18 6 15 6 12a6 6 0 0 1 .34-2" />
    <path d="M8.65 22c.21-.66.45-1.32.57-2" />
    <path d="M9 6.8a6 6 0 0 1 9 5.2v2" />
  </Icon>
);
const IconShieldCheck = () => (
  <Icon>
    <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67 0C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" />
    <path d="m9 12 2 2 4-4" />
  </Icon>
);
const IconLock = () => (
  <Icon size={17}>
    <circle cx="12" cy="16" r="1" />
    <rect x="3" y="10" width="18" height="12" rx="2" />
    <path d="M7 10V7a5 5 0 0 1 10 0v3" />
  </Icon>
);
const IconClock = () => (
  <Icon>
    <circle cx="12" cy="12" r="10" />
    <path d="M12 6v6l4 2" />
  </Icon>
);
const IconCheckCircle = () => (
  <Icon size={18}>
    <path d="M21.8 10A10 10 0 1 1 17 3.34" />
    <path d="m9 11 3 3L22 4" />
  </Icon>
);
const IconChevron = () => (
  <Icon size={13}>
    <path d="m9 18 6-6-6-6" />
  </Icon>
);
const IconPlus = ({ size = 15 }: { size?: number }) => (
  <Icon size={size}>
    <path d="M5 12h14M12 5v14" />
  </Icon>
);
const IconCheck = () => (
  <Icon size={12}>
    <path d="M20 6 9 17l-5-5" />
  </Icon>
);

/** ตัวย่อบนอวาตาร์ — ตัวแรกของสองคำแรกของชื่อ (fallback ไปอีเมล) */
function initialsOf(me: Me | null): string {
  const name = (me?.full_name ?? "").trim();
  if (name) {
    const parts = name.split(/\s+/).filter(Boolean);
    return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
  }
  return (me?.email ?? "?").slice(0, 2).toUpperCase();
}

function scrollTo(id: string) {
  document
    .getElementById(id)
    ?.scrollIntoView({ behavior: "smooth", block: "center" });
}

export function AccountView() {
  const [me, setMe] = useState<Me | null>(null);

  const [supported, setSupported] = useState<boolean | null>(null);
  const [platformAvailable, setPlatformAvailable] = useState(false);
  const [passkeys, setPasskeys] = useState<PasskeyInfo[]>([]);
  const [maxPasskeys, setMaxPasskeys] = useState(10);
  const [backupStatus, setBackupStatus] = useState<BackupCodesStatus | null>(
    null
  );
  const [totp, setTotp] = useState<TotpStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [deviceName, setDeviceName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  // เปลี่ยนบัญชี Google (re-link) — step-up ด้วย passkey แล้ว redirect ไป Google
  const [googleBusy, setGoogleBusy] = useState(false);
  const [googleVerifying, setGoogleVerifying] = useState(false);
  const [googleErr, setGoogleErr] = useState<string | null>(null);

  const handleChangeGoogle = async () => {
    setGoogleErr(null);
    setGoogleBusy(true);
    try {
      const res = await changeGoogleStart(setGoogleVerifying);
      window.location.href = res.start_url; // นำทางออกจากหน้านี้
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
    clientFetch<Me>("/auth/me")
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [list, bc, ts] = await Promise.all([
        listPasskeys(),
        fetchBackupCodesStatus().catch(() => null),
        totpStatus().catch(() => null),
      ]);
      setPasskeys(list.passkeys);
      setMaxPasskeys(list.max);
      setBackupStatus(bc);
      setTotp(ts);
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

  // มาจากการ์ด SecurityOnboarding (?setup=passkey|totp|both) — scroll ไปการ์ดที่เลือก
  useEffect(() => {
    if (typeof window === "undefined") return;
    const setup = new URLSearchParams(window.location.search).get("setup");
    if (!setup) return;
    const targetId = setup === "totp" ? "setup-totp" : "setup-passkey";
    const t = setTimeout(() => scrollTo(targetId), 300);
    return () => clearTimeout(t);
  }, []);

  const atMax = passkeys.length >= maxPasskeys;
  const hasPasskey = passkeys.length > 0;
  const totpOn = totp?.enabled === true;
  const readyCount = 1 + (hasPasskey ? 1 : 0) + (totpOn ? 1 : 0);
  const hasCodes = (backupStatus?.generation ?? 0) > 0;
  // Google เชื่อมอยู่แล้วเสมอ (login เข้ามาได้ = ผูกแล้ว) จึงนับเป็น 1 วิธีพื้นฐาน

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

  const regenerate = async () => {
    if (!confirm("สร้าง backup codes ชุดใหม่? codes เก่าทั้งหมดจะใช้ไม่ได้")) return;
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
  };

  return (
    <div className="sc">
      <Topbar title="บัญชีของฉัน" />

      <div className="cx-document">
        {/* ── หัวหน้า: ตัวตน + ตัวเลขสำคัญ 3 ช่อง ── */}
        <section className="cx-account-cover">
          <div className="cx-account-avatar mono">{initialsOf(me)}</div>

          <div className="cx-account-title">
            <span className="mono">
              {me?.is_hub_admin ? "ADMIN IDENTITY" : "DEVELOPER IDENTITY"}
            </span>
            <h2>{me?.full_name || me?.email || "—"}</h2>
            <p>
              <IconMail />
              {me?.email ?? "—"}
            </p>
          </div>

          <div className="cx-account-facts">
            <span>
              <small className="mono">ROLE</small>
              <b>
                {me
                  ? me.is_hub_admin
                    ? "ผู้ดูแลระบบ (Hub Admin)"
                    : "นักพัฒนา (Developer)"
                  : "—"}
              </b>
            </span>
            <span>
              <small className="mono">PASSKEY</small>
              <b className={hasPasskey ? "signal" : undefined}>
                {hasPasskey && <span className="cx-dot" />}
                {loading ? "—" : `${passkeys.length}/${maxPasskeys} อุปกรณ์`}
              </b>
            </span>
            <span>
              <small className="mono">รหัสสำรอง</small>
              <b
                className={hasCodes && !backupStatus?.low ? "signal" : undefined}
              >
                {loading
                  ? "—"
                  : hasCodes
                    ? `เหลือ ${backupStatus?.remaining}/${backupStatus?.total}`
                    : "ยังไม่มี"}
              </b>
            </span>
          </div>
        </section>

        <section className="cx-account-layout">
          <div className="cx-account-main">
            {/* ── สรุปวิธีเข้าสู่ระบบ + ทางลัดไปการ์ดจัดการ ── */}
            <article className="cx-panel cx-account-security">
              <header>
                <div>
                  <span className="mono">authentication methods</span>
                  <h2>วิธีเข้าสู่ระบบ</h2>
                </div>
                <span className="cx-security-count mono">
                  {readyCount} METHODS READY
                </span>
              </header>

              <div className="cx-method-list">
                <div>
                  <i className="passkey">
                    <IconFingerprint />
                  </i>
                  <span>
                    <b>Passkey</b>
                    <small>
                      {loading
                        ? "กำลังโหลด"
                        : hasPasskey
                          ? `${passkeys.length} อุปกรณ์` +
                            (platformAvailable
                              ? " · เครื่องนี้รองรับ biometric"
                              : "")
                          : "ยังไม่ได้ตั้งค่า"}
                    </small>
                  </span>
                  {hasPasskey ? (
                    <span className="cx-chip signal">
                      <IconCheck />
                      พร้อมใช้งาน
                    </span>
                  ) : (
                    <span className="cx-chip warn">ยังไม่ตั้งค่า</span>
                  )}
                  <button
                    type="button"
                    onClick={() => scrollTo("setup-passkey")}
                  >
                    จัดการ
                    <IconChevron />
                  </button>
                </div>

                <div>
                  <i className="authenticator">
                    <IconShieldCheck />
                  </i>
                  <span>
                    <b>Authenticator (TOTP)</b>
                    <small>
                      {totpOn
                        ? "แอป authenticator เชื่อมแล้ว"
                        : "รหัส 6 หลักจากแอป — ใช้เป็นตัวสำรองของ Passkey"}
                    </small>
                  </span>
                  {totpOn ? (
                    <span className="cx-chip signal">
                      <IconCheck />
                      ตั้งค่าแล้ว
                    </span>
                  ) : (
                    <span className="cx-chip warn">ยังไม่ตั้งค่า</span>
                  )}
                  <button type="button" onClick={() => scrollTo("setup-totp")}>
                    จัดการ
                    <IconChevron />
                  </button>
                </div>

                <div>
                  <i className="google">
                    <b>G</b>
                  </i>
                  <span>
                    <b>Google Workspace</b>
                    <small className="mono">{me?.email ?? "—"}</small>
                  </span>
                  <span className="cx-chip signal">
                    <IconCheck />
                    เชื่อมต่อแล้ว
                  </span>
                  <button
                    type="button"
                    onClick={handleChangeGoogle}
                    disabled={googleBusy}
                  >
                    {googleVerifying
                      ? "ยืนยัน"
                      : googleBusy
                        ? "กำลังเริ่ม"
                        : "เชื่อมใหม่"}
                    <IconChevron />
                  </button>
                </div>
              </div>

              {googleErr && (
                <div className="cx-inline-error">
                  {googleErr}
                  {googleErr.includes("Passkey") && (
                    <>
                      {" · "}
                      <a href="/auth/passkey/recover">Account Recovery</a>
                    </>
                  )}
                </div>
              )}

              {supported && !hasPasskey && (
                <button
                  type="button"
                  className="cx-add-method"
                  onClick={() => {
                    setShowAdd(true);
                    scrollTo("setup-passkey");
                  }}
                >
                  <IconPlus />
                  <span>
                    <b>เพิ่มวิธียืนยันตัวตน</b>
                    <small>
                      แนะนำให้มีอย่างน้อย 2 วิธี เพื่อกู้คืนบัญชีได้เมื่อทำอุปกรณ์หาย
                    </small>
                  </span>
                  <IconChevron />
                </button>
              )}
            </article>

            {/* ── Passkey: รายการอุปกรณ์ + ฟอร์มเพิ่ม ── */}
            <article className="cx-panel" id="setup-passkey">
              <header>
                <div>
                  <span className="mono">passkey devices</span>
                  <h2>Passkey ของคุณ</h2>
                </div>
                {supported && !atMax && !showAdd && (
                  <button
                    type="button"
                    className="cx-panel-action"
                    onClick={() => setShowAdd(true)}
                  >
                    <IconPlus size={13} />
                    เพิ่ม Passkey
                  </button>
                )}
              </header>

              {supported === false && (
                <div className="cx-inline-error">
                  เบราว์เซอร์นี้ไม่รองรับ Passkey — ใช้ Chrome, Edge, Safari หรือ
                  Firefox เวอร์ชันใหม่
                </div>
              )}

              {loading ? (
                <div className="cx-empty sm">
                  <strong>กำลังโหลด</strong>
                </div>
              ) : passkeys.length === 0 ? (
                <div className="cx-empty">
                  <IconFingerprint size={26} />
                  <strong>ยังไม่มี Passkey</strong>
                  <span>เพิ่มเพื่อเข้าสู่ระบบแบบไม่ใช้รหัสผ่าน</span>
                </div>
              ) : (
                <div className="cx-passkey-list">
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
                <div className="cx-add-form">
                  <label htmlFor="pk-name">ชื่ออุปกรณ์ใหม่</label>
                  <div>
                    <input
                      id="pk-name"
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
                    />
                    <button
                      type="button"
                      className="cx-primary"
                      onClick={handleRegister}
                      disabled={busy || !deviceName.trim()}
                    >
                      {busy ? "กำลังลงทะเบียน" : "ลงทะเบียน"}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setShowAdd(false);
                        setDeviceName("");
                        setError(null);
                      }}
                      disabled={busy}
                    >
                      ยกเลิก
                    </button>
                  </div>
                </div>
              )}

              {atMax && (
                <div className="cx-inline-warn">
                  ถึงจำนวนสูงสุด {maxPasskeys} อุปกรณ์ — ลบอุปกรณ์เก่าก่อนเพิ่มใหม่
                </div>
              )}

              {error && <div className="cx-inline-error">{error}</div>}
            </article>

            {/* ── Authenticator (TOTP) ── */}
            <div id="setup-totp">
              <TotpCard />
            </div>

            {/* ── Always-2FA + ปัจจัยที่ต้องการ ── */}
            <SecurityCard />
          </div>

          <aside className="cx-account-side">
            <article className="cx-panel cx-account-profile">
              <header>
                <div>
                  <span className="mono">profile</span>
                  <h2>ข้อมูลบัญชี</h2>
                </div>
              </header>
              <dl>
                <div>
                  <dt>ชื่อที่แสดง</dt>
                  <dd>{me?.full_name ?? "—"}</dd>
                </div>
                <div>
                  <dt>อีเมล</dt>
                  <dd className="mono">{me?.email ?? "—"}</dd>
                </div>
                <div>
                  <dt>ประเภทผู้ใช้</dt>
                  <dd>{me?.user_type ?? "—"}</dd>
                </div>
                <div>
                  <dt>คณะ / หน่วยงาน</dt>
                  <dd>{me?.faculty ?? "—"}</dd>
                </div>
              </dl>
            </article>

            <article className="cx-panel cx-account-policy">
              <header>
                <div>
                  <span className="mono">security policy</span>
                  <h2>การยืนยันตัวตน</h2>
                </div>
                <IconLock />
              </header>
              <div className="cx-trust-window">
                <IconClock />
                <span>
                  <b>Trust window</b>
                  <small>ไม่ถามซ้ำบนอุปกรณ์ที่เพิ่งยืนยันไปแล้ว</small>
                </span>
                <strong className="mono">15 MIN</strong>
              </div>
            </article>

            <article className="cx-panel cx-account-recovery">
              <header>
                <div>
                  <span className="mono">account recovery</span>
                  <h2>รหัสสำรอง</h2>
                </div>
                {hasCodes && (
                  <button
                    type="button"
                    className="cx-panel-action"
                    onClick={regenerate}
                    disabled={busy}
                  >
                    สร้างใหม่
                  </button>
                )}
              </header>
              <div>
                <IconCheckCircle />
                <span>
                  <b>
                    {loading
                      ? "—"
                      : hasCodes
                        ? backupStatus?.low
                          ? "ใกล้หมด"
                          : "พร้อมใช้งาน"
                        : "ยังไม่ได้สร้าง"}
                  </b>
                  <small>
                    {hasCodes
                      ? `เหลือ ${backupStatus?.remaining} จาก ${backupStatus?.total} ชุด · ใช้ได้ครั้งเดียวต่อรหัส`
                      : "ระบบสร้างให้อัตโนมัติเมื่อลงทะเบียน Passkey ครั้งแรก"}
                  </small>
                </span>
              </div>
            </article>
          </aside>
        </section>
      </div>

      {backupCodes && (
        <BackupCodesModal
          codes={backupCodes}
          onAcknowledged={() => setBackupCodes(null)}
        />
      )}
    </div>
  );
}
