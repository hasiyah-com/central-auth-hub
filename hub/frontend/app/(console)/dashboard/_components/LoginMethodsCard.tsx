"use client";

/**
 * Login Methods card (dashboard) — admin เลือกว่าระบบยอมให้ login ผ่านวิธีไหน.
 *   - Google / Passkey toggle (ต้องเปิด ≥ 1)
 *   - Save = critical action → step-up (passkey/OTP) ผ่าน mutateWithStepup
 *   - หลังบันทึก: backend kick ทุก session ทุก subsystem → user login ใหม่ตามที่เลือก
 */

import { useEffect, useState } from "react";
import { clientFetch } from "@/lib/api";
import { mutateWithStepup } from "@/lib/passkey";

type Policy = { google: boolean; passkey: boolean };

type SaveResult = {
  policy: Policy;
  changed: boolean;
  total_sessions_closed: number;
  total_jti_revoked: number;
  message: string;
};

function errText(e: unknown, fallback: string): string {
  if (typeof e === "object" && e && "detail" in e) {
    const d = (e as { detail: unknown }).detail;
    if (typeof d === "string") return d;
  }
  return e instanceof Error ? e.message : fallback;
}

export function LoginMethodsCard() {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [draft, setDraft] = useState<Policy | null>(null);
  const [busy, setBusy] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(
    null
  );

  useEffect(() => {
    clientFetch<Policy>("/admin/auth-policy")
      .then((p) => {
        setPolicy(p);
        setDraft(p);
      })
      .catch(() => {
        setMsg({ kind: "err", text: "โหลดการตั้งค่าไม่สำเร็จ" });
      });
  }, []);

  const dirty =
    policy && draft
      ? policy.google !== draft.google || policy.passkey !== draft.passkey
      : false;
  const noneSelected = draft ? !draft.google && !draft.passkey : false;

  const toggle = (key: keyof Policy) => {
    if (!draft) return;
    setMsg(null);
    setDraft({ ...draft, [key]: !draft[key] });
  };

  const save = async () => {
    if (!draft || noneSelected) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await mutateWithStepup<SaveResult>(
        "/admin/auth-policy",
        {
          method: "PUT",
          body: JSON.stringify(draft),
        },
        setVerifying
      );
      setPolicy(r.policy);
      setDraft(r.policy);
      setMsg({ kind: "ok", text: r.message });
    } catch (e) {
      setMsg({ kind: "err", text: errText(e, "บันทึกไม่สำเร็จ") });
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    if (policy) setDraft(policy);
    setMsg(null);
  };

  const methods: {
    key: keyof Policy;
    label: string;
    desc: string;
    /** สีไทล์ไอคอนตามดีไซน์ — passkey (teal) / google (น้ำเงิน) */
    iconTone: "passkey" | "google";
    icon: React.ReactNode;
    recommended: boolean;
  }[] = [
    {
      key: "passkey",
      label: "Passkey",
      desc: "WebAuthn · phishing-resistant",
      iconTone: "passkey",
      icon: (
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M2.586 17.414A2 2 0 0 0 2 18.828V21a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h1a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h.172a2 2 0 0 0 1.414-.586l.814-.814a6.5 6.5 0 1 0-4-4z" />
          <circle cx="16.5" cy="7.5" r=".5" fill="currentColor" />
        </svg>
      ),
      recommended: true,
    },
    {
      key: "google",
      label: "Google Workspace",
      desc: "OAuth 2.0 · บัญชีองค์กร",
      iconTone: "google",
      icon: "G",
      recommended: false,
    },
  ];

  return (
    <section>
      {verifying && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
          <div className="bg-white border border-ink-200 px-6 py-5 flex items-center gap-3 text-sm text-ink-700">
            <span className="animate-pulse text-lg">🔐</span>
            กำลังยืนยันด้วย Passkey… ทำตามที่อุปกรณ์แจ้ง
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-head">
          <div>
            <span className="overline">auth policy</span>
            <h2>วิธีการเข้าสู่ระบบ</h2>
          </div>
          <svg
            width="19"
            height="19"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="text-ink-400"
            aria-hidden="true"
          >
            <circle cx="12" cy="16" r="1" />
            <rect x="3" y="10" width="18" height="12" rx="2" />
            <path d="M7 10V7a5 5 0 0 1 10 0v3" />
          </svg>
        </div>

        {methods.map((m) => {
          const on = draft?.[m.key] ?? false;
          return (
            <div key={m.key} className="auth-method">
              <div className={`method-icon ${m.iconTone}`}>{m.icon}</div>
              <div className="min-w-0">
                <strong>{m.label}</strong>
                <span className="truncate">{m.desc}</span>
              </div>
              {m.recommended ? <span className="recommended">แนะนำ</span> : <span />}
              <button
                type="button"
                role="switch"
                aria-checked={on}
                aria-label={`${on ? "ปิด" : "เปิด"}ใช้งาน ${m.label}`}
                onClick={() => toggle(m.key)}
                disabled={busy}
                className="auth-switch"
              >
                <i />
              </button>
            </div>
          );
        })}

        <div className="stepup">
          <div>
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" />
              <path d="m9 12 2 2 4-4" />
            </svg>
            Step-up verification
          </div>
          <b className="mono">TRUST WINDOW · 15 MIN</b>
        </div>

        <div className="px-4 pb-4 pt-3">
          {noneSelected && (
          <div className="mb-3 text-xs text-rose-700 bg-rose-50 border border-rose-200 p-2.5">
            ⚠️ ต้องเปิดอย่างน้อย 1 วิธี — ไม่งั้นจะไม่มีใคร login เข้าระบบได้
          </div>
        )}

        {msg && (
          <div
            className={
              "mb-3 text-xs p-2.5 border " +
              (msg.kind === "ok"
                ? "text-emerald-800 bg-emerald-50 border-emerald-200"
                : "text-rose-700 bg-rose-50 border-rose-200")
            }
          >
            {msg.kind === "ok" ? "✓ " : "✗ "}
            {msg.text}
          </div>
        )}

        <div className="flex items-center gap-2">
          <button
            onClick={save}
            disabled={busy || !dirty || noneSelected}
            className="px-4 py-2 bg-ink-900 hover:bg-ink-800 disabled:bg-ink-300 disabled:cursor-not-allowed text-white text-sm font-bold transition"
          >
            {busy ? "กำลังบันทึก…" : "บันทึก + ตัด session ทั้งหมด"}
          </button>
          {dirty && !busy && (
            <button
              onClick={reset}
              className="px-3 py-2 border border-ink-200 hover:bg-ink-50 text-sm text-ink-600"
            >
              ยกเลิก
            </button>
          )}
          {!policy && (
            <span className="text-xs text-ink-400">กำลังโหลด…</span>
          )}
          </div>
        </div>
      </div>
    </section>
  );
}
