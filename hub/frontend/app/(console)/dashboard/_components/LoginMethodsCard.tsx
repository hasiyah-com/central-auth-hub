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

function MethodIcon({ method }: { method: keyof Policy }) {
  if (method === "passkey") {
    return (
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" className="h-5 w-5">
        <circle cx="8" cy="12" r="3.25" stroke="currentColor" strokeWidth="1.8" />
        <path
          d="M11.25 12H21m-3 0v3m-3-3v2"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" className="h-5 w-5">
      <path
        d="M20.6 12.2c0-.7-.1-1.3-.2-1.9H12v3.5h4.8a4.1 4.1 0 0 1-1.8 2.7v2.3h2.9c1.7-1.6 2.7-3.8 2.7-6.6Z"
        fill="currentColor"
      />
      <path
        d="M12 21c2.4 0 4.5-.8 5.9-2.2L15 16.5c-.8.5-1.8.9-3 .9-2.3 0-4.3-1.6-5-3.7H4v2.4A9 9 0 0 0 12 21Z"
        fill="currentColor"
        opacity=".78"
      />
      <path
        d="M7 13.7a5.4 5.4 0 0 1 0-3.4V7.9H4a9 9 0 0 0 0 8.2l3-2.4Z"
        fill="currentColor"
        opacity=".55"
      />
      <path
        d="M12 6.6c1.3 0 2.5.5 3.4 1.3L18 5.3A8.7 8.7 0 0 0 12 3a9 9 0 0 0-8 4.9l3 2.4c.7-2.1 2.7-3.7 5-3.7Z"
        fill="currentColor"
        opacity=".9"
      />
    </svg>
  );
}

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
    recommended?: boolean;
  }[] = [
    {
      key: "passkey",
      label: "Passkey",
      desc: "WebAuthn · ป้องกัน phishing",
      recommended: true,
    },
    {
      key: "google",
      label: "Google Workspace",
      desc: "OAuth 2.0 · บัญชีองค์กร",
    },
  ];

  return (
    <section className="mb-8">
      <h2 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
        วิธีการเข้าสู่ระบบ (Login Methods)
      </h2>

      {verifying && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-2xl px-6 py-5 shadow-xl flex items-center gap-3 text-sm text-ink-700">
            <span className="animate-pulse text-lg">🔐</span>
            กำลังยืนยันด้วย Passkey… ทำตามที่อุปกรณ์แจ้ง
          </div>
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-ink-200 bg-white shadow-sm">
        <div className="divide-y divide-ink-100">
          {methods.map((m) => {
            const on = draft?.[m.key] ?? false;
            return (
              <button
                key={m.key}
                type="button"
                onClick={() => toggle(m.key)}
                disabled={busy}
                aria-pressed={on}
                className={
                  "group grid min-h-[76px] w-full grid-cols-[44px_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 sm:px-5 " +
                  (on ? "bg-white hover:bg-emerald-50/40" : "bg-ink-50/50 hover:bg-ink-50")
                }
              >
                <span
                  className={
                    "flex h-11 w-11 items-center justify-center rounded-xl transition-colors " +
                    (on
                      ? "bg-emerald-50 text-emerald-600"
                      : "bg-ink-100 text-ink-400")
                  }
                >
                  <MethodIcon method={m.key} />
                </span>

                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="text-sm font-bold text-ink-900">{m.label}</span>
                    {m.recommended && (
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-700 ring-1 ring-inset ring-emerald-200">
                        แนะนำ
                      </span>
                    )}
                  </div>
                  <p className="mt-1 truncate text-xs text-ink-500">{m.desc}</p>
                </div>

                <span className="flex min-w-[98px] items-center justify-end gap-3">
                  <span
                    className={
                      "hidden w-12 text-right text-xs font-semibold sm:block " +
                      (on ? "text-emerald-700" : "text-ink-400")
                    }
                  >
                    {on ? "เปิด" : "ปิด"}
                  </span>
                  <span
                    className={
                      "relative h-6 w-11 flex-none rounded-full transition-colors duration-200 " +
                      (on ? "bg-emerald-500" : "bg-ink-300")
                    }
                  >
                    <span
                      className={
                        "absolute top-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform duration-200 " +
                        (on ? "translate-x-[22px]" : "translate-x-0.5")
                      }
                    />
                  </span>
                </span>
              </button>
            );
          })}
        </div>

        {noneSelected && (
          <div className="mx-4 mt-4 text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-lg p-2.5 sm:mx-5">
            ⚠️ ต้องเปิดอย่างน้อย 1 วิธี — ไม่งั้นจะไม่มีใคร login เข้าระบบได้
          </div>
        )}

        {msg && (
          <div
            className={
              "mx-4 mt-4 text-xs rounded-lg p-2.5 border sm:mx-5 " +
              (msg.kind === "ok"
                ? "text-emerald-800 bg-emerald-50 border-emerald-200"
                : "text-rose-700 bg-rose-50 border-rose-200")
            }
          >
            {msg.kind === "ok" ? "✓ " : "✗ "}
            {msg.text}
          </div>
        )}

        <div className="flex min-h-[62px] flex-wrap items-center gap-2 border-t border-ink-100 bg-ink-50/40 px-4 py-3 sm:px-5">
          <button
            onClick={save}
            disabled={busy || !dirty || noneSelected}
            className="px-4 py-2 rounded-lg bg-ink-900 hover:bg-ink-800 disabled:bg-ink-300 disabled:cursor-not-allowed text-white text-sm font-bold transition"
          >
            {busy ? "กำลังบันทึก…" : "บันทึก + ตัด session ทั้งหมด"}
          </button>
          {dirty && !busy && (
            <button
              onClick={reset}
              className="px-3 py-2 rounded-lg border border-ink-200 hover:bg-ink-50 text-sm text-ink-600"
            >
              ยกเลิก
            </button>
          )}
          {!policy && (
            <span className="text-xs text-ink-400">กำลังโหลด…</span>
          )}
        </div>
      </div>
    </section>
  );
}
