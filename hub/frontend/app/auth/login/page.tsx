"use client";

import { useEffect, useState, type ReactNode } from "react";
import {
  isPasskeySupported,
  loginWithPasskey,
  loginWithPasskeyDiscoverable,
} from "@/lib/passkey";

const HUB_URL = process.env.NEXT_PUBLIC_HUB_URL || "http://localhost:8000";

function LoginSignal() {
  return <span className="login-signal" aria-hidden="true"><i /></span>;
}

function LineIcon({ children, size = 18 }: { children: ReactNode; size?: number }) {
  return <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>;
}

export default function LoginPage() {
  const [passkeySupported, setPasskeySupported] = useState<boolean | null>(null);
  const [showPasskeyDialog, setShowPasskeyDialog] = useState(false);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // แจ้งผลจาก flow เปลี่ยนบัญชี Google (redirect กลับมาที่หน้า login)
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; text: string } | null>(
    null
  );
  // Global auth-policy — admin อาจปิด Google หรือ Passkey
  const [policy, setPolicy] = useState<{ google: boolean; passkey: boolean }>({
    google: true,
    passkey: true,
  });

  useEffect(() => {
    // อ่านผล change-google จาก query (redirect กลับมาแบบ full-page — ไม่ใช้ useSearchParams
    // เลี่ยง Suspense boundary requirement)
    const q = new URLSearchParams(window.location.search);
    if (q.get("google_changed") === "1") {
      setNotice({
        kind: "ok",
        text: "เปลี่ยนบัญชี Google สำเร็จ — เข้าสู่ระบบด้วยบัญชีใหม่",
      });
    } else if ((q.get("error") || "").startsWith("change_google")) {
      setNotice({
        kind: "err",
        text: "เปลี่ยนบัญชี Google ไม่สำเร็จ — ลิงก์อาจหมดอายุ หรือบัญชีนั้นถูกใช้แล้ว กรุณาลองใหม่",
      });
    }
  }, []);

  useEffect(() => {
    setPasskeySupported(isPasskeySupported());
    // อ่าน policy ผ่าน Next rewrite (/api/hub → backend) — ไม่มี CORS
    fetch("/api/hub/auth/policy")
      .then((r) => (r.ok ? r.json() : null))
      .then((p) => {
        if (p && typeof p.google === "boolean" && typeof p.passkey === "boolean") {
          setPolicy(p);
        }
      })
      .catch(() => {
        /* fail-safe: คงค่า default (เปิดทั้งคู่) */
      });
  }, []);

  const persistAndRedirect = async (token: string, isAdmin: boolean) => {
    const setRes = await fetch("/api/set-token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ token }),
    });
    if (!setRes.ok) {
      const body = await setRes.json().catch(() => ({}));
      throw new Error(body.error || "ไม่สามารถบันทึก session ได้");
    }
    window.location.href = isAdmin ? "/dashboard" : "/developer/subsystems";
  };

  const friendlyErr = (e: unknown): string => {
    const msg =
      e instanceof Error
        ? e.message
        : typeof e === "object" && e && "detail" in e
          ? String((e as { detail: unknown }).detail)
          : "ไม่สามารถเข้าสู่ระบบได้ กรุณาลองใหม่อีกครั้ง";
    // OWASP anti-enumeration: auth-failure ทุกกรณีใช้ข้อความเดียวกัน (generic)
    // — ไม่บอกว่า email มี/ไม่มี passkey หรือ credential ผิด
    if (
      msg.includes("invalid_credential") ||
      msg.includes("assertion_verify_failed")
    )
      return "ไม่สามารถเข้าสู่ระบบได้ กรุณาลองใหม่อีกครั้ง";
    if (msg.includes("challenge_expired")) return "Session หมดอายุ กรุณาลองใหม่";
    return msg;
  };

  const handlePasskeyLogin = async () => {
    if (!email.trim()) {
      setError("กรุณากรอก email");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const result = await loginWithPasskey(email.trim());
      await persistAndRedirect(result.access_token, result.user.is_hub_admin);
    } catch (e) {
      setError(friendlyErr(e));
      setBusy(false);
    }
  };

  const handleDiscoverable = async () => {
    setError(null);
    setBusy(true);
    try {
      const result = await loginWithPasskeyDiscoverable();
      await persistAndRedirect(result.access_token, result.user.is_hub_admin);
    } catch (e) {
      setError(friendlyErr(e));
      setBusy(false);
    }
  };

  return (
    <main className="login-page">
      <div className="login-grain" /><div className="login-glow glow-one" /><div className="login-glow glow-two" />
      <header className="login-topbar">
        <a className="login-brand" href="/" aria-label="Central Auth Hub">
          <span className="login-brand-icon"><LineIcon size={20}><path d="M5 5v14M19 5v14M5 12h14" /></LineIcon><LoginSignal /></span>
          <span><strong>HUB</strong><small>IDENTITY CONTROL</small></span>
        </a>
        <div className="login-system-status"><LoginSignal /><span>AUTH GATEWAY</span><b className="mono">ONLINE</b></div>
      </header>

      <section className="login-stage">
        <div className="login-context">
          <div className="context-kicker"><LineIcon size={14}><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3M22 12h-3M12 22v-3M2 12h3"/></LineIcon><span className="mono">SECURE ACCESS · TH-SOUTH-01</span></div>
          <h1>ยืนยันตัวตน<br />ก่อนเข้าสู่<span> Signal Room</span></h1>
          <p>ศูนย์ควบคุม Identity, Permission และ Security Operations ของมหาวิทยาลัย</p>
          <div className="trust-rail" aria-label="คุณสมบัติความปลอดภัย">
            <div className="rail-line"><i/><i/><i/></div>
            <div className="trust-point active"><span><LineIcon><path d="M7 12a5 5 0 0 1 10 0v5M5 12a7 7 0 0 1 14 0v4M9 12a3 3 0 0 1 6 0v8M12 12v9"/></LineIcon></span><div><b>Phishing-resistant</b><small>Passkey · WebAuthn</small></div></div>
            <div className="trust-point"><span><LineIcon><path d="M12 3 20 6v5c0 5-3 8-8 10-5-2-8-5-8-10V6l8-3Z"/><path d="m8 12 2.5 2.5L16 9"/></LineIcon></span><div><b>Risk-aware access</b><small>4-layer scoring ก่อนอนุญาต</small></div></div>
            <div className="trust-point"><span><LineIcon><rect x="5" y="10" width="14" height="11"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></LineIcon></span><div><b>Audit protected</b><small>Append-only hash chain</small></div></div>
          </div>
        </div>

        <section className="login-panel" aria-labelledby="login-title">
          <div className="panel-scanline" />
          <div className="login-panel-head"><span className="login-overline mono">ADMIN AUTHENTICATION</span><h2 id="login-title">เข้าสู่ระบบผู้ดูแล</h2><p>ใช้บัญชีมหาวิทยาลัยที่ได้รับสิทธิ์เท่านั้น</p></div>

          {notice && <div className={notice.kind === "ok" ? "login-ready" : "login-error"}>{notice.kind === "ok" ? "✓" : "⚠"} {notice.text}</div>}

          {policy.passkey && passkeySupported && (
            <div>
              {!showPasskeyDialog ? (
                <button className="passkey-button" type="button" onClick={() => setShowPasskeyDialog(true)}><LineIcon><circle cx="8" cy="15" r="4"/><path d="M12 15h9M18 15v3M15 15v2"/></LineIcon><span>ดำเนินการต่อด้วย Passkey</span><b aria-hidden="true">→</b></button>
              ) : (
                <div className="login-passkey-form">
                  <div className="login-passkey-head"><b>PASSKEY VERIFICATION</b><button type="button" onClick={() => { setShowPasskeyDialog(false); setError(null); setEmail(""); }} disabled={busy}>ยกเลิก</button></div>
                  <label className="login-field"><span>อีเมลมหาวิทยาลัย</span><div className={error ? "field-control invalid" : "field-control"}><LineIcon size={17}><rect x="3" y="5" width="18" height="14"/><path d="m3 7 9 6 9-6"/></LineIcon><input type="email" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@pnu.ac.th" disabled={busy} onKeyDown={(e) => { if (e.key === "Enter" && !busy) handlePasskeyLogin(); }} autoComplete="username webauthn"/><span className="mono">PNU</span></div></label>
                  {error && <div className="login-error" role="alert">{error}</div>}
                  <button className="passkey-button" type="button" onClick={handlePasskeyLogin} disabled={busy || !email.trim()}><span>{busy ? "กำลังตรวจสอบ Passkey..." : "ยืนยันและเข้าสู่ระบบ"}</span><b aria-hidden="true">→</b></button>
                  <button className="discoverable-button" type="button" onClick={handleDiscoverable} disabled={busy}>ใช้ Passkey ที่บันทึกในอุปกรณ์นี้</button>
                </div>
              )}
            </div>
          )}

          {policy.passkey && passkeySupported === false && <div className={policy.google ? "login-error login-warning" : "login-error"}>เบราว์เซอร์นี้ไม่รองรับ Passkey{policy.google ? " — ใช้ Google Workspace แทนได้" : " และ Google login ถูกปิด"}</div>}

          {policy.google && <><div className="login-divider"><span>หรือ</span></div><a href={`${HUB_URL}/auth/google/login`} className="google-button"><span className="google-g">G</span><span>เข้าสู่ระบบด้วย Google Workspace</span><b aria-hidden="true">→</b></a></>}

          <div className="login-help">
            {policy.passkey && passkeySupported && <a href="/auth/passkey/recover">ใช้ Passkey ไม่ได้หรือกู้คืนบัญชี</a>}
            <span>·</span><a href={`${HUB_URL}/auth/credentials/setup`}>เพิ่มวิธียืนยันตัวตน</a>
          </div>
          <div className="policy-stamp"><LineIcon size={14}><path d="M12 3 20 6v5c0 5-3 8-8 10-5-2-8-5-8-10V6l8-3Z"/><path d="m8 12 2.5 2.5L16 9"/></LineIcon><span>Auth policy loaded</span><code className="mono">passkey:{policy.passkey ? "on" : "off"} · google:{policy.google ? "on" : "off"}</code></div>
        </section>
      </section>
      <footer className="login-footer"><span>Central Auth Hub</span><code className="mono">TLS 1.3 · WEBAUTHN · OAUTH 2.0</code><span>Princess of Naradhiwas University</span></footer>
    </main>
  );
}
