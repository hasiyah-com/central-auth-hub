"use client";

/**
 * Access Policy card — เลือกว่าใครเข้า subsystem ได้ (explicit/all/role/attribute)
 * + จัดการ Roster API key (prefix + rotate).
 * เปลี่ยน policy = critical action → mutateWithStepup (PATCH /developer/subsystems/{id}).
 */

import { useEffect, useState } from "react";
import { clientFetch } from "@/lib/api";
import { mutateWithStepup } from "@/lib/passkey";

type PolicyConfig = { roles?: string[]; faculty?: string[]; major?: string[] };

type Props = {
  subId: string;
  policy: string;
  config: PolicyConfig | null | undefined;
  apiKeyPrefix: string | null | undefined;
  onReload: () => void;
};

const USER_TYPES = ["student", "teacher", "staff", "admin"];

const POLICY_META: Record<string, { label: string; desc: string; icon: string }> = {
  explicit: { label: " Whitelist", desc: "เฉพาะรายชื่อ CSV", icon: "📋" },
  all: { label: "All Users", desc: "ผู้ใช้ทุกคนที่ active เข้าได้", icon: "🌐" },
  role: { label: "Role", desc: "เฉพาะ Role ที่เลือก", icon: "👥" },
  attribute: { label: "Attribute", desc: "เฉพาะคณะ/สาขา", icon: "🎯" },
};

function errText(e: unknown, fb: string): string {
  if (typeof e === "object" && e && "detail" in e) {
    const d = (e as { detail: unknown }).detail;
    if (typeof d === "string") return d;
  }
  return e instanceof Error ? e.message : fb;
}

export function AccessPolicyCard({ subId, policy, config, apiKeyPrefix, onReload }: Props) {
  const [draft, setDraft] = useState(policy || "explicit");
  const [roles, setRoles] = useState<string[]>(config?.roles || []);
  const [faculty, setFaculty] = useState((config?.faculty || []).join(", "));
  const [major, setMajor] = useState((config?.major || []).join(", "));
  const [busy, setBusy] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  // rotate key
  const [newKey, setNewKey] = useState<string | null>(null);
  const [rotating, setRotating] = useState(false);

  useEffect(() => {
    setDraft(policy || "explicit");
    setRoles(config?.roles || []);
    setFaculty((config?.faculty || []).join(", "));
    setMajor((config?.major || []).join(", "));
  }, [policy, config]);

  const toggleRole = (r: string) =>
    setRoles((cur) => (cur.includes(r) ? cur.filter((x) => x !== r) : [...cur, r]));

  const splitList = (s: string) =>
    s.split(",").map((x) => x.trim()).filter(Boolean);

  const buildConfig = (): PolicyConfig | null => {
    if (draft === "role") return { roles };
    if (draft === "attribute") {
      const c: PolicyConfig = {};
      if (splitList(faculty).length) c.faculty = splitList(faculty);
      if (splitList(major).length) c.major = splitList(major);
      return c;
    }
    return null;
  };

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await mutateWithStepup(
        `/developer/subsystems/${subId}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            access_policy: draft,
            access_policy_config: buildConfig(),
          }),
        },
        setVerifying
      );
      setMsg({ kind: "ok", text: "บันทึก Access Policy แล้ว — session ที่ active ถูกตัดเพื่อ re-auth" });
      onReload();
    } catch (e) {
      setMsg({ kind: "err", text: errText(e, "บันทึกไม่สำเร็จ") });
    } finally {
      setBusy(false);
    }
  };

  const rotateKey = async () => {
    if (!confirm("ออก API key ใหม่? key เดิมจะใช้ไม่ได้ทันที")) return;
    setRotating(true);
    setMsg(null);
    try {
      const r = await clientFetch<{ api_key: string }>(
        `/developer/subsystems/${subId}/rotate-api-key`,
        { method: "POST" }
      );
      setNewKey(r.api_key);
      onReload();
    } catch (e) {
      setMsg({ kind: "err", text: errText(e, "rotate ไม่สำเร็จ") });
    } finally {
      setRotating(false);
    }
  };

  return (
    <section className="bg-white rounded-xl border border-ink-200 shadow-sm p-5 space-y-4">
      {verifying && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-2xl px-6 py-5 shadow-xl flex items-center gap-3 text-sm text-ink-700">
            <span className="animate-pulse text-lg">🔐</span>
            กำลังยืนยันด้วย Passkey…
          </div>
        </div>
      )}

      <div>
        <h3 className="text-sm font-extrabold text-ink-800">นโยบายการเข้าถึง (Access Policy)</h3>
        {/* <p className="text-xs text-ink-500 mt-0.5">ใครเข้าใช้ subsystem นี้ได้ — ตรวจตอน login + ใช้กับ Roster API</p> */}
      </div>

      {/* policy selector */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {Object.entries(POLICY_META).map(([key, m]) => (
          <button
            key={key}
            onClick={() => setDraft(key)}
            className={
              "flex items-start gap-2.5 p-3 rounded-lg border-2 text-left transition " +
              (draft === key ? "border-brand-400 bg-brand-50" : "border-ink-200 hover:border-ink-300")
            }
          >
            <span className="text-xl leading-none">{m.icon}</span>
            <div className="min-w-0">
              <div className="text-sm font-bold text-ink-900">{m.label}</div>
              <div className="text-[11px] text-ink-500 mt-0.5 leading-snug">{m.desc}</div>
            </div>
          </button>
        ))}
      </div>

      {/* config per policy */}
      {draft === "role" && (
        <div className="p-3 rounded-lg bg-ink-50 border border-ink-100">
          <div className="text-[11px] font-bold text-ink-500 uppercase tracking-wider mb-2">
            เลือกบทบาทที่เข้าได้
          </div>
          <div className="flex flex-wrap gap-2">
            {USER_TYPES.map((r) => (
              <button
                key={r}
                onClick={() => toggleRole(r)}
                className={
                  "px-3 py-1.5 rounded-full text-xs font-semibold border transition " +
                  (roles.includes(r)
                    ? "bg-emerald-100 border-emerald-300 text-emerald-800"
                    : "bg-white border-ink-200 text-ink-500 hover:border-ink-300")
                }
              >
                {roles.includes(r) ? "✓ " : ""}{r}
              </button>
            ))}
          </div>
          {roles.length === 0 && (
            <div className="text-[11px] text-rose-600 mt-2">⚠️ ต้องเลือกอย่างน้อย 1 บทบาท</div>
          )}
        </div>
      )}

      {draft === "attribute" && (
        <div className="p-3 rounded-lg bg-ink-50 border border-ink-100 space-y-2">
          <div>
            <div className="text-[11px] font-bold text-ink-500 uppercase tracking-wider mb-1">คณะ (faculty) — คั่นด้วย ,</div>
            <input
              value={faculty}
              onChange={(e) => setFaculty(e.target.value)}
              placeholder="วิศวกรรมศาสตร์, แพทยศาสตร์"
              className="w-full px-3 py-2 rounded-lg border border-ink-200 text-sm focus:ring-2 focus:ring-brand-500"
            />
          </div>
          <div>
            <div className="text-[11px] font-bold text-ink-500 uppercase tracking-wider mb-1">สาขา (major) — คั่นด้วย ,</div>
            <input
              value={major}
              onChange={(e) => setMajor(e.target.value)}
              placeholder="คอมพิวเตอร์, จิตเวช"
              className="w-full px-3 py-2 rounded-lg border border-ink-200 text-sm focus:ring-2 focus:ring-brand-500"
            />
          </div>
          <div className="text-[11px] text-ink-400">ปล่อยว่างทั้งคู่ไม่ได้ — ต้องมีอย่างน้อย 1 เงื่อนไข</div>
        </div>
      )}

      {draft === "explicit" && (
        <div className="text-xs text-ink-500 bg-ink-50 border border-ink-100 rounded-lg p-3">
          ใช้รายชื่อใน Whitelist ด้านล่าง (เพิ่มทีละคน / CSV)
        </div>
      )}
      {draft === "all" && (
        <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3">
          ⚠️ ผู้ใช้ <strong>ทุกคน</strong> ที่ active เข้าได้ — ใช้ Whitelist เป็น deny-list เพื่อ ban รายคน
        </div>
      )}

      {msg && (
        <div
          className={
            "text-xs rounded-lg p-2.5 border " +
            (msg.kind === "ok"
              ? "text-emerald-800 bg-emerald-50 border-emerald-200"
              : "text-rose-700 bg-rose-50 border-rose-200")
          }
        >
          {msg.kind === "ok" ? "✓ " : "✗ "}{msg.text}
        </div>
      )}

      <button
        onClick={save}
        disabled={busy || (draft === "role" && roles.length === 0)}
        className="px-4 py-2 rounded-lg bg-ink-900 hover:bg-ink-800 disabled:bg-ink-300 text-white text-sm font-bold transition"
      >
        {busy ? "กำลังบันทึก…" : "บันทึก Access Policy"}
      </button>

      {/* ── Roster API key ── */}
      <div className="pt-4 border-t border-ink-100">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <h4 className="text-sm font-bold text-ink-800">🔑 Roster API key</h4>
            <p className="text-[11px] text-ink-500 mt-0.5">
              {/* ดึงรายชื่อผู้ใช้ที่เข้าได้ (GET /api/v1/roster) — ใช้ตอน subsystem สร้าง record ล่วงหน้า */}
            </p>
          </div>
          <button
            onClick={rotateKey}
            disabled={rotating}
            className="px-3 py-1.5 rounded-lg border border-ink-200 hover:bg-ink-50 text-xs font-semibold text-ink-700 disabled:opacity-50"
          >
            {rotating ? "…" : apiKeyPrefix ? "🔄 ออก key ใหม่" : "+ สร้าง key"}
          </button>
        </div>
        <div className="mt-2 font-mono text-xs text-ink-500">
          {apiKeyPrefix ? `${apiKeyPrefix}••••••••••••••••••••` : "— ยังไม่มี key —"}
        </div>

        {newKey && (
          <div className="mt-2 p-3 rounded-lg bg-emerald-50 border border-emerald-200">
            <div className="text-[11px] font-bold text-emerald-800 mb-1">
              ✓ API key ใหม่ — แสดงครั้งเดียว เก็บไว้ให้ดี
            </div>
            <div className="flex items-center gap-2">
              <code className="flex-1 font-mono text-xs bg-white rounded px-2 py-1.5 border border-emerald-200 break-all">
                {newKey}
              </code>
              <button
                onClick={() => navigator.clipboard?.writeText(newKey)}
                className="px-2 py-1.5 rounded bg-emerald-600 text-white text-xs font-semibold"
              >
                คัดลอก
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
