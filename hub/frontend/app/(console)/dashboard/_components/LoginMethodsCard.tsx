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
    icon: string;
  }[] = [
    {
      key: "passkey",
      label: "Passkey",
      desc: "ยืนยันตัวตนด้วย biometric / security key (WebAuthn)",
      icon: "🔑",
    },
    {
      key: "google",
      label: "Google",
      desc: "เข้าสู่ระบบด้วยบัญชี Google (OAuth)",
      icon: "🔵",
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

      <div className="bg-white rounded-xl border border-ink-200 p-5 shadow-sm">
        <p className="text-sm text-ink-500 mb-4">
          เลือกว่าจะให้ผู้ใช้เข้าสู่ระบบผ่านวิธีไหนได้บ้าง — มีผลกับ
          <strong className="text-ink-700"> ทุกระบบย่อย</strong> และ Admin Console
          เมื่อบันทึก ทุก session ที่ใช้งานอยู่จะถูกตัด เพื่อให้ login ใหม่ตามที่เลือก
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
          {methods.map((m) => {
            const on = draft?.[m.key] ?? false;
            return (
              <button
                key={m.key}
                onClick={() => toggle(m.key)}
                disabled={busy}
                className={
                  "flex items-start gap-3 p-4 rounded-xl border-2 text-left transition disabled:opacity-50 " +
                  (on
                    ? "border-emerald-400 bg-emerald-50"
                    : "border-ink-200 bg-ink-50/40 hover:border-ink-300")
                }
              >
                <span className="text-2xl leading-none">{m.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-ink-900">{m.label}</span>
                    <span
                      className={
                        "text-[10px] font-bold px-1.5 py-0.5 rounded-full " +
                        (on
                          ? "bg-emerald-200 text-emerald-900"
                          : "bg-ink-200 text-ink-500")
                      }
                    >
                      {on ? "เปิด" : "ปิด"}
                    </span>
                  </div>
                  <div className="text-xs text-ink-500 mt-1 leading-relaxed">
                    {m.desc}
                  </div>
                </div>
                <span
                  className={
                    "mt-1 w-10 h-6 rounded-full relative transition flex-none " +
                    (on ? "bg-emerald-500" : "bg-ink-300")
                  }
                >
                  <span
                    className={
                      "absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-all " +
                      (on ? "left-[18px]" : "left-0.5")
                    }
                  />
                </span>
              </button>
            );
          })}
        </div>

        {noneSelected && (
          <div className="mb-3 text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-lg p-2.5">
            ⚠️ ต้องเปิดอย่างน้อย 1 วิธี — ไม่งั้นจะไม่มีใคร login เข้าระบบได้
          </div>
        )}

        {msg && (
          <div
            className={
              "mb-3 text-xs rounded-lg p-2.5 border " +
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
