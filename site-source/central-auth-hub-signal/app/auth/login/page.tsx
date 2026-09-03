"use client";

import { FormEvent, useState } from "react";
import {
  ArrowRight, CheckCircle2, Command, Fingerprint, KeyRound,
  LoaderCircle, LockKeyhole, Mail, Radar, ShieldCheck,
} from "lucide-react";

function LoginSignal() {
  return <span className="login-signal" aria-hidden="true"><i /></span>;
}

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");

  const submitPasskey = (event: FormEvent) => {
    event.preventDefault();
    if (!email.trim()) {
      setStatus("error");
      return;
    }
    setStatus("loading");
    window.setTimeout(() => setStatus("ready"), 950);
  };

  return (
    <main className="login-page">
      <div className="login-grain" />
      <div className="login-glow glow-one" />
      <div className="login-glow glow-two" />

      <header className="login-topbar">
        <a className="login-brand" href="/" aria-label="Central Auth Hub">
          <span className="login-brand-icon"><Command size={20} /><LoginSignal /></span>
          <span><strong>HUB</strong><small>IDENTITY CONTROL</small></span>
        </a>
        <div className="login-system-status"><LoginSignal /><span>AUTH GATEWAY</span><b className="mono">ONLINE</b></div>
      </header>

      <section className="login-stage">
        <div className="login-context">
          <div className="context-kicker"><Radar size={14} /><span className="mono">SECURE ACCESS · TH-SOUTH-01</span></div>
          <h1>ยืนยันตัวตน<br />ก่อนเข้าสู่<span> Signal Room</span></h1>
          <p>ศูนย์ควบคุม Identity, Permission และ Security Operations ของมหาวิทยาลัย</p>

          <div className="trust-rail" aria-label="คุณสมบัติความปลอดภัย">
            <div className="rail-line"><i /><i /><i /></div>
            <div className="trust-point active"><span><Fingerprint size={17} /></span><div><b>Phishing-resistant</b><small>Passkey · WebAuthn</small></div></div>
            <div className="trust-point"><span><ShieldCheck size={17} /></span><div><b>Risk-aware access</b><small>4-layer scoring ก่อนอนุญาต</small></div></div>
            <div className="trust-point"><span><LockKeyhole size={17} /></span><div><b>Audit protected</b><small>Append-only hash chain</small></div></div>
          </div>
        </div>

        <section className="login-panel" aria-labelledby="login-title">
          <div className="panel-scanline" />
          <div className="login-panel-head">
            <span className="login-overline mono">ADMIN AUTHENTICATION</span>
            <h2 id="login-title">เข้าสู่ระบบผู้ดูแล</h2>
            <p>ใช้บัญชีมหาวิทยาลัยที่ได้รับสิทธิ์เท่านั้น</p>
          </div>

          <form onSubmit={submitPasskey} noValidate>
            <label className="login-field">
              <span>อีเมลมหาวิทยาลัย</span>
              <div className={status === "error" ? "field-control invalid" : "field-control"}>
                <Mail size={17} />
                <input
                  type="email"
                  value={email}
                  onChange={(event) => { setEmail(event.target.value); if (status !== "idle") setStatus("idle"); }}
                  placeholder="name@pnu.ac.th"
                  autoComplete="username webauthn"
                  aria-describedby={status === "error" ? "login-error" : undefined}
                />
                <span className="mono">PNU</span>
              </div>
            </label>

            {status === "error" && <div className="login-error" id="login-error" role="alert">ไม่สามารถดำเนินการได้ โปรดตรวจสอบข้อมูลหรือลองวิธีอื่น</div>}
            {status === "ready" && <div className="login-ready" role="status"><CheckCircle2 size={15} />พร้อมเรียกใช้งาน Passkey บนอุปกรณ์นี้</div>}

            <button className="passkey-button" type="submit" disabled={status === "loading"}>
              {status === "loading" ? <LoaderCircle className="button-loader" size={18} /> : <KeyRound size={18} />}
              <span>{status === "loading" ? "กำลังตรวจสอบนโยบาย..." : "ดำเนินการต่อด้วย Passkey"}</span>
              {status !== "loading" && <ArrowRight size={16} />}
            </button>

            <button className="discoverable-button" type="button" onClick={() => setStatus("ready")}>
              <Fingerprint size={17} />ใช้ Passkey ที่บันทึกในอุปกรณ์นี้
            </button>

            <div className="login-divider"><span>หรือ</span></div>

            <button className="google-button" type="button">
              <span className="google-g">G</span>
              <span>เข้าสู่ระบบด้วย Google Workspace</span>
              <ArrowRight size={15} />
            </button>
          </form>

          <div className="login-help">
            <a href="#recover">ใช้ Passkey ไม่ได้หรือกู้คืนบัญชี</a>
            <span>·</span>
            <a href="#support">ติดต่อผู้ดูแลระบบ</a>
          </div>

          <div className="policy-stamp">
            <ShieldCheck size={14} />
            <span>Auth policy loaded</span>
            <code className="mono">passkey:on · google:on</code>
          </div>
        </section>
      </section>

      <footer className="login-footer">
        <span>Central Auth Hub</span>
        <code className="mono">TLS 1.3 · WEBAUTHN · OAUTH 2.0</code>
        <span>Princess of Naradhiwas University</span>
      </footer>
    </main>
  );
}
