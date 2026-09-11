// "use client";

// import { useEffect, useState } from "react";
// import {
//   isPasskeySupported,
//   loginWithPasskey,
//   loginWithPasskeyDiscoverable,
// } from "@/lib/passkey";


// const HUB_URL = process.env.NEXT_PUBLIC_HUB_URL || "http://localhost:8000";

// export default function LoginPage() {
//   const [passkeySupported, setPasskeySupported] = useState<boolean | null>(null);
//   const [showPasskeyDialog, setShowPasskeyDialog] = useState(false);
//   const [email, setEmail] = useState("");
//   const [busy, setBusy] = useState(false);
//   const [error, setError] = useState<string | null>(null);
//   // แจ้งผลจาก flow เปลี่ยนบัญชี Google (redirect กลับมาที่หน้า login)
//   const [notice, setNotice] = useState<{ kind: "ok" | "err"; text: string } | null>(
//     null
//   );
//   // Global auth-policy — admin อาจปิด Google หรือ Passkey
//   const [policy, setPolicy] = useState<{ google: boolean; passkey: boolean }>({
//     google: true,
//     passkey: true,
//   });

//   useEffect(() => {
//     // อ่านผล change-google จาก query (redirect กลับมาแบบ full-page — ไม่ใช้ useSearchParams
//     // เลี่ยง Suspense boundary requirement)
//     const q = new URLSearchParams(window.location.search);
//     if (q.get("google_changed") === "1") {
//       setNotice({
//         kind: "ok",
//         text: "เปลี่ยนบัญชี Google สำเร็จ — เข้าสู่ระบบด้วยบัญชีใหม่",
//       });
//     } else if ((q.get("error") || "").startsWith("change_google")) {
//       setNotice({
//         kind: "err",
//         text: "เปลี่ยนบัญชี Google ไม่สำเร็จ — ลิงก์อาจหมดอายุ หรือบัญชีนั้นถูกใช้แล้ว กรุณาลองใหม่",
//       });
//     }
//   }, []);

//   useEffect(() => {
//     setPasskeySupported(isPasskeySupported());
//     // อ่าน policy ผ่าน Next rewrite (/api/hub → backend) — ไม่มี CORS
//     fetch("/api/hub/auth/policy")
//       .then((r) => (r.ok ? r.json() : null))
//       .then((p) => {
//         if (p && typeof p.google === "boolean" && typeof p.passkey === "boolean") {
//           setPolicy(p);
//         }
//       })
//       .catch(() => {
//         /* fail-safe: คงค่า default (เปิดทั้งคู่) */
//       });
//   }, []);

//   const persistAndRedirect = async (token: string, isAdmin: boolean) => {
//     const setRes = await fetch("/api/set-token", {
//       method: "POST",
//       headers: { "Content-Type": "application/json" },
//       credentials: "include",
//       body: JSON.stringify({ token }),
//     });
//     if (!setRes.ok) {
//       const body = await setRes.json().catch(() => ({}));
//       throw new Error(body.error || "ไม่สามารถบันทึก session ได้");
//     }
//     window.location.href = isAdmin ? "/dashboard" : "/developer/subsystems";
//   };

//   const friendlyErr = (e: unknown): string => {
//     const msg =
//       e instanceof Error
//         ? e.message
//         : typeof e === "object" && e && "detail" in e
//           ? String((e as { detail: unknown }).detail)
//           : "ไม่สามารถเข้าสู่ระบบได้ กรุณาลองใหม่อีกครั้ง";
//     // OWASP anti-enumeration: auth-failure ทุกกรณีใช้ข้อความเดียวกัน (generic)
//     // — ไม่บอกว่า email มี/ไม่มี passkey หรือ credential ผิด
//     if (
//       msg.includes("invalid_credential") ||
//       msg.includes("assertion_verify_failed")
//     )
//       return "ไม่สามารถเข้าสู่ระบบได้ กรุณาลองใหม่อีกครั้ง";
//     if (msg.includes("challenge_expired")) return "Session หมดอายุ กรุณาลองใหม่";
//     return msg;
//   };

//   const handlePasskeyLogin = async () => {
//     if (!email.trim()) {
//       setError("กรุณากรอก email");
//       return;
//     }
//     setError(null);
//     setBusy(true);
//     try {
//       const result = await loginWithPasskey(email.trim());
//       await persistAndRedirect(result.access_token, result.user.is_hub_admin);
//     } catch (e) {
//       setError(friendlyErr(e));
//       setBusy(false);
//     }
//   };

//   const handleDiscoverable = async () => {
//     setError(null);
//     setBusy(true);
//     try {
//       const result = await loginWithPasskeyDiscoverable();
//       await persistAndRedirect(result.access_token, result.user.is_hub_admin);
//     } catch (e) {
//       setError(friendlyErr(e));
//       setBusy(false);
//     }
//   };

//   return (
//     <main className="min-h-screen grid place-items-center bg-gradient-to-br from-ink-900 via-ink-800 to-brand-900 px-4">
//       <div className="w-full max-w-md bg-white rounded-2xl shadow-2xl overflow-hidden">
//         <div className="px-8 pt-10 pb-8">
//           <div className="flex items-center gap-3 mb-6">
//             <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-brand-600 to-brand-900 grid place-items-center text-white text-xl font-bold">
//               H
//             </div>
//             <div>
//               <div className="text-xs text-ink-500 font-semibold uppercase tracking-wider">
//                 Central Auth Hub
//               </div>
//               <div className="text-lg font-bold text-ink-900">Admin Console</div>
//             </div>
//           </div>

//           <h1 className="text-2xl font-extrabold text-ink-900 mb-2">
//             เข้าสู่ระบบรวมศูนย์
//           </h1>
//           <p className="text-sm text-ink-500 mb-8">
//             {/* ลงชื่อเข้าใช้ระบบด้วย Passkey หรือบัญชี Google ที่ลงทะเบียนไว้ */}
//           </p>

//           {notice && (
//             <div
//               className={
//                 "mb-6 p-3 rounded-xl text-sm border " +
//                 (notice.kind === "ok"
//                   ? "bg-emerald-50 border-emerald-200 text-emerald-800"
//                   : "bg-rose-50 border-rose-200 text-rose-800")
//               }
//             >
//               {notice.text}
//             </div>
//           )}

//           {/* Passkey login (Phase 2) — conditional on browser support + policy */}
//           {policy.passkey && passkeySupported && !showPasskeyDialog && (
//             <button
//               onClick={() => setShowPasskeyDialog(true)}
//               className="w-full flex items-center justify-center gap-3 px-4 py-3 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold transition mb-3"
//             >
//               <span>Sign in with Passkey</span>
//             </button>
//           )}

//           {/* Passkey email-first dialog */}
//           {policy.passkey && showPasskeyDialog && (
//             <div className="mb-3 p-4 rounded-xl border-2 border-emerald-200 bg-emerald-50 space-y-3">
//               <div className="flex items-center justify-between">
//                 <div className="font-semibold text-emerald-900">
//                  Sign in with Passkey
//                 </div>
//                 <button
//                   onClick={() => {
//                     setShowPasskeyDialog(false);
//                     setError(null);
//                     setEmail("");
//                   }}
//                   disabled={busy}
//                   className="text-emerald-700 hover:text-emerald-900 text-sm"
//                 >
//                   ยกเลิก
//                 </button>
//               </div>
//               <p className="text-xs text-emerald-800">
//                 {/* กรอก email ของคุณ แล้วระบบจะถาม biometric / security key */}
//               </p>
//               <input
//                 type="email"
//                 autoFocus
//                 value={email}
//                 onChange={(e) => setEmail(e.target.value)}
//                 placeholder="you@uni.ac.th"
//                 disabled={busy}
//                 onKeyDown={(e) => {
//                   if (e.key === "Enter" && !busy) handlePasskeyLogin();
//                 }}
//                 className="w-full px-3 py-2 border border-emerald-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 bg-white"
//               />
//               {error && (
//                 <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2">
//                   {error}
//                 </div>
//               )}
//               <button
//                 onClick={handlePasskeyLogin}
//                 disabled={busy || !email.trim()}
//                 className={`w-full py-2.5 rounded-lg font-semibold transition ${
//                   busy || !email.trim()
//                     ? "bg-emerald-300 text-white cursor-not-allowed"
//                     : "bg-emerald-600 text-white hover:bg-emerald-700"
//                 }`}
//               >
//                 {busy ? "กำลังตรวจ Passkey…" : "ดำเนินการต่อ"}
//               </button>
//               <div className="flex items-center gap-2 text-[10px] text-emerald-700">
//                 <span className="flex-1 h-px bg-emerald-200" />
//                 หรือ
//                 <span className="flex-1 h-px bg-emerald-200" />
//               </div>
//               <button
//                 onClick={handleDiscoverable}
//                 disabled={busy}
//                 className="w-full py-2 rounded-lg text-sm font-medium text-emerald-700 hover:bg-emerald-100 border border-emerald-200 transition disabled:opacity-50"
//               >
//                 เข้าโดยไม่กรอก email (เลือก passkey จากอุปกรณ์)
//               </button>
//             </div>
//           )}

//           {policy.passkey && policy.google && passkeySupported === false && (
//             <div className="mb-3 p-3 text-xs text-amber-900 bg-amber-50 border border-amber-200 rounded-lg">
//               เบราว์เซอร์นี้ไม่รองรับ Passkey — กรุณาใช้ Google login แทน
//             </div>
//           )}

//           {/* Passkey ปิด + browser ไม่รองรับ → เตือนว่าใช้ไม่ได้ */}
//           {!policy.google && policy.passkey && passkeySupported === false && (
//             <div className="mb-3 p-3 text-xs text-rose-900 bg-rose-50 border border-rose-200 rounded-lg">
//               เบราว์เซอร์นี้ไม่รองรับ Passkey และผู้ดูแลปิด Google login —
//               กรุณาใช้เบราว์เซอร์ที่รองรับ Passkey
//             </div>
//           )}

//           {/* Google login — fallback ทุก browser (เคารพ policy) */}
//           {policy.google && (
//           <a
//             href={`${HUB_URL}/auth/google/login`}
//             className="w-full flex items-center justify-center gap-3 px-4 py-3 rounded-xl bg-ink-900 hover:bg-ink-800 text-white font-semibold transition"
//           >
//             <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
//               <path
//                 d="M21.6 12.227c0-.709-.064-1.39-.182-2.045H12v3.868h5.382a4.6 4.6 0 0 1-1.996 3.018v2.51h3.232c1.891-1.742 2.982-4.305 2.982-7.35Z"
//                 fill="#4285F4"
//               />
//               <path
//                 d="M12 22c2.7 0 4.964-.895 6.618-2.423l-3.232-2.509c-.895.6-2.04.955-3.386.955-2.605 0-4.81-1.76-5.595-4.123H3.064v2.59A9.996 9.996 0 0 0 12 22Z"
//                 fill="#34A853"
//               />
//               <path
//                 d="M6.405 13.9a6.003 6.003 0 0 1 0-3.8V7.51H3.064a9.996 9.996 0 0 0 0 8.98l3.341-2.59Z"
//                 fill="#FBBC05"
//               />
//               <path
//                 d="M12 5.977c1.468 0 2.786.505 3.823 1.496l2.868-2.868C16.96 2.99 14.695 2 12 2A9.996 9.996 0 0 0 3.064 7.51l3.341 2.59C7.19 7.736 9.395 5.977 12 5.977Z"
//                 fill="#EA4335"
//               />
//             </svg>
//             <span>Sign in with Google</span>
//           </a>
//           )}

//           {/* LINE login — ปิดชั่วคราว (Q3 decision 2026-06-10)
//               email scope ยังแก้ไม่ตก, code อยู่ใน git/backend จะกลับมาเมื่อแก้ได้

//           <a href={`${HUB_URL}/auth/line/login`} className="mt-3 ...">
//             Sign in with LINE
//           </a>
//           */}

//           {/* เพิ่มการยืนยันตัวตน — ตั้ง passkey/TOTP โดยไม่เข้า console
//               ใช้ได้ทุก role รวมนักศึกษา (backend ไม่ออก JWT ที่ intent นี้) */}
//           <a
//             href={`${HUB_URL}/auth/credentials/setup`}
//             className="mt-3 w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl border border-emerald-300 text-emerald-700 font-semibold hover:bg-emerald-50 transition"
//           >
//             <span>เพิ่มการยืนยันตัวตน</span>
//           </a>
//           <p className="mt-1.5 text-[11px] text-ink-400 text-center">
//             {/* ตั้ง Passkey หรือ Authenticator — นักศึกษาก็ใช้ได้ */}
//           </p>

//           <div className="mt-6 text-xs text-ink-400 text-center">
//             © 2024 Central Auth Hub
//           </div>
//           {policy.passkey && passkeySupported && (
//             <div className="mt-2 text-center">
//               <a
//                 href="/auth/passkey/recover"
//                 className="text-xs text-emerald-600 hover:text-emerald-700"
//               >
//                 ทำ Passkey หาย? กู้บัญชี
//               </a>
//             </div>
//           )}
//         </div>

//         <div className="px-8 py-5 bg-ink-50 border-t border-ink-100">
//           <div className="text-xs text-ink-500 flex items-center justify-between">
//             <span>OAuth 2.0 · PKCE · JWT RS256 · WebAuthn</span>
//             <span className="font-mono">v0.5.0</span>
//           </div>
//         </div>
//       </div>
//     </main>
//   );
// }

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

          {notice && <div className={notice.kind === "ok" ? "login-ready" : "login-error"}>{notice.text}</div>}

          {policy.passkey && passkeySupported && (
            <div>
              {!showPasskeyDialog ? (
                <button className="passkey-button" type="button" onClick={() => setShowPasskeyDialog(true)}><LineIcon><circle cx="8" cy="15" r="4"/><path d="M12 15h9M18 15v3M15 15v2"/></LineIcon><span>ดำเนินการต่อด้วย Passkey</span><b aria-hidden="true">→</b></button>
              ) : (
                <div className="login-passkey-form">
                  <div className="login-passkey-head"><b>PASSKEY VERIFICATION</b><button type="button" onClick={() => { setShowPasskeyDialog(false); setError(null); setEmail(""); }} disabled={busy}>ยกเลิก</button></div>
                  <label className="login-field"><span>อีเมลมหาวิทยาลัย</span><div className={error ? "field-control invalid" : "field-control"}><LineIcon size={17}><rect x="3" y="5" width="18" height="14"/><path d="m3 7 9 6 9-6"/></LineIcon><input type="email" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@uni.ac.th" disabled={busy} onKeyDown={(e) => { if (e.key === "Enter" && !busy) handlePasskeyLogin(); }} autoComplete="username webauthn"/><span className="mono">PNU</span></div></label>
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
