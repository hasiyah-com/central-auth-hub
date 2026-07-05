"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";
import { mutateWithStepup } from "@/lib/passkey";

// ALLOWED_SCOPES — ต้องตรงกับ backend developer.py
const SCOPE_OPTIONS: Array<{ key: string; label: string; desc: string }> = [
  { key: "email", label: "Email", desc: "อีเมลของผู้ใช้" },
  { key: "name", label: "Full Name", desc: "ชื่อ-นามสกุล" },
  { key: "student_id", label: "Student ID", desc: "รหัสนักศึกษา (เฉพาะนักศึกษา)" },
  { key: "employee_id", label: "Employee ID", desc: "รหัสบุคลากร" },
  { key: "faculty", label: "Faculty", desc: "คณะ" },
  { key: "major", label: "Major", desc: "สาขาวิชา" },
  { key: "year", label: "Year", desc: "ชั้นปี (เฉพาะนักศึกษา)" },
  { key: "position", label: "Position", desc: "ตำแหน่ง (เฉพาะบุคลากร)" },
  { key: "phone", label: "Phone", desc: "เบอร์โทรศัพท์" },
  { key: "address", label: "Address", desc: "ที่อยู่" },
];

type RegisterResponse = {
  subsystem_id: string;
  client_id: string;
  status: string;
  message: string;
  secret_delivery: "email" | "url"; // pragma: allowlist secret
  secret_sent_to?: string;
  secret_retrieval_url?: string;
  warning?: string;
  note?: string;
  webhook_endpoints?: { access_revoked: string; access_updated: string };
  webhook_note?: string;
  api_key?: string;
  api_key_note?: string;
};

const POLICY_OPTIONS: Array<{ key: string; label: string; desc: string; icon: string }> = [
  { key: "explicit", label: "Whitelist", desc: "เฉพาะรายชื่อ CSV ", icon: "📋" },
  { key: "all", label: "All Users", desc: "ผู้ใช้ทุกคนที่ active เข้าได้", icon: "🌐" },
  { key: "role", label: "Role", desc: "เฉพาะ Role ที่เลือก", icon: "👥" },
  { key: "attribute", label: "Attribute", desc: "เฉพาะคณะ/สาขา", icon: "🎯" },
];
const USER_TYPES = ["student", "teacher", "staff", "admin"];

export default function NewSubsystemPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [redirectUris, setRedirectUris] = useState<string[]>([""]);
  const [scope, setScope] = useState<Set<string>>(new Set(["email", "name"]));
  const [accessPolicy, setAccessPolicy] = useState("explicit");
  const [policyRoles, setPolicyRoles] = useState<Set<string>>(new Set());
  const [policyFaculty, setPolicyFaculty] = useState("");
  const [policyMajor, setPolicyMajor] = useState("");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RegisterResponse | null>(null);

  function addUri() {
    setRedirectUris((u) => [...u, ""]);
  }
  function removeUri(i: number) {
    setRedirectUris((u) => u.filter((_, idx) => idx !== i));
  }
  function setUri(i: number, v: string) {
    setRedirectUris((u) => u.map((x, idx) => (idx === i ? v : x)));
  }

  function toggleScope(key: string) {
    setScope((s) => {
      const next = new Set(s);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const cleanUris = redirectUris.map((u) => u.trim()).filter(Boolean);
    if (cleanUris.length === 0) {
      setError("ต้องมี redirect URI อย่างน้อย 1 ตัว");
      return;
    }
    if (scope.size === 0) {
      setError("ต้องเลือก scope อย่างน้อย 1 ตัว");
      return;
    }

    // สร้าง access_policy_config ตาม policy ที่เลือก
    const splitList = (s: string) =>
      s.split(",").map((x) => x.trim()).filter(Boolean);
    let policyConfig: Record<string, string[]> | null = null;
    if (accessPolicy === "role") {
      if (policyRoles.size === 0) {
        setError("policy 'ตามบทบาท' ต้องเลือกบทบาทอย่างน้อย 1");
        return;
      }
      policyConfig = { roles: Array.from(policyRoles) };
    } else if (accessPolicy === "attribute") {
      const fac = splitList(policyFaculty);
      const maj = splitList(policyMajor);
      if (fac.length === 0 && maj.length === 0) {
        setError("policy 'ตามคุณสมบัติ' ต้องระบุคณะหรือสาขาอย่างน้อย 1 เงื่อนไข");
        return;
      }
      policyConfig = {};
      if (fac.length) policyConfig.faculty = fac;
      if (maj.length) policyConfig.major = maj;
    }

    setBusy(true);
    try {
      // Option C — inline step-up: ถ้า 403 → verify Passkey ในหน้า แล้ว retry
      // (ไม่ redirect → ข้อมูลในฟอร์มไม่หาย)
      const r = await mutateWithStepup<RegisterResponse>(
        "/developer/subsystems",
        {
          method: "POST",
          body: JSON.stringify({
            name: name.trim(),
            description: description.trim() || null,
            redirect_uris: cleanUris,
            scope: Array.from(scope),
            access_policy: accessPolicy,
            access_policy_config: policyConfig,
            access_revoke_webhook_url: webhookUrl.trim() || null,
          }),
        },
        setVerifying
      );
      setResult(r);
    } catch (e) {
      const detail = (e as { detail?: unknown })?.detail;
      const code =
        typeof detail === "object" && detail
          ? (detail as { code?: string }).code
          : undefined;
      if (code === "no_passkey") {
        setError(
          "ต้องมี Passkey เพื่อยืนยันการลงทะเบียน — ตั้งค่าที่หน้าบัญชี/ความปลอดภัย หรือใช้ Account Recovery"
        );
      } else if (e instanceof DOMException && e.name === "NotAllowedError") {
        setError("ยกเลิกการยืนยัน Passkey — ลองอีกครั้ง (ข้อมูลในฟอร์มยังอยู่)");
      } else {
        setError(typeof detail === "string" ? detail : "ลงทะเบียนไม่สำเร็จ");
      }
    } finally {
      setBusy(false);
      setVerifying(false);
    }
  }

  // ── Success screen ───────────────────────────────────────
  if (result) {
    const viaEmail = result.secret_delivery === "email"; // pragma: allowlist secret
    return (
      <>
        <Topbar title="ลงทะเบียนสำเร็จ" />
        <main className="p-8 max-w-3xl mx-auto w-full">
          <div className="bg-white rounded-xl border border-emerald-200 shadow-sm p-8">
            <div className="flex items-center gap-3 mb-5">
              <div className="w-12 h-12 rounded-full bg-emerald-100 grid place-items-center text-2xl">
                ✓
              </div>
              <div>
                <h2 className="text-xl font-extrabold text-ink-900">
                  ลงทะเบียนเรียบร้อย
                </h2>
                <p className="text-sm text-ink-500">
                  ระบบเข้าสู่สถานะ <strong>รออนุมัติ</strong> จาก Hub Admin
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6 bg-ink-50 p-4 rounded-lg">
              <div>
                <div className="text-[10px] font-bold uppercase tracking-wider text-ink-500 mb-1">
                  Client ID
                </div>
                <div className="font-mono text-sm text-ink-900 break-all">
                  {result.client_id}
                </div>
              </div>
              <div>
                <div className="text-[10px] font-bold uppercase tracking-wider text-ink-500 mb-1">
                  Subsystem ID
                </div>
                <div className="font-mono text-xs text-ink-700 break-all">
                  {result.subsystem_id}
                </div>
              </div>
            </div>

            {result.api_key && (
              <div className="rounded-lg bg-emerald-50 border border-emerald-300 p-5 mb-6">
                <div className="text-xl mb-1">🔑</div>
                <h3 className="font-bold text-emerald-900 mb-1">Roster API Key</h3>
                <p className="text-xs text-emerald-700 mb-2">
                  {result.api_key_note || "ใช้ดึงรายชื่อผู้ใช้ผ่าน GET /api/v1/roster"} —
                  <strong> แสดงครั้งเดียว</strong>
                </p>
                <div className="bg-white border border-emerald-200 rounded p-3 font-mono text-[11px] break-all text-emerald-900">
                  {result.api_key}
                </div>
              </div>
            )}

            {viaEmail ? (
              <div className="rounded-lg bg-brand-50 border border-brand-200 p-5 mb-6">
                <div className="text-2xl mb-2">📧</div>
                <h3 className="font-bold text-brand-900 mb-1">
                  ลิงก์ดู Client Secret ส่งทาง Email แล้ว
                </h3>
                <p className="text-sm text-brand-700 mb-2">
                  ส่งไปที่ <strong>{result.secret_sent_to}</strong>
                </p>
                <ul className="text-xs text-brand-800 space-y-1 list-disc list-inside">
                  <li>ตรวจ inbox + spam folder</li>
                  <li>ลิงก์หมดอายุใน 15 นาที</li>
                  <li>secret แสดงเพียงครั้งเดียว — copy ใส่ .env ทันที</li>
                  <li>ถ้าลืม ต้องลงทะเบียนระบบใหม่ทั้งหมด</li>
                </ul>
              </div>
            ) : (
              <div className="rounded-lg bg-rose-50 border border-rose-300 p-5 mb-6">
                <div className="text-2xl mb-2">⚠️</div>
                <h3 className="font-bold text-rose-900 mb-1">
                  Email ส่งไม่สำเร็จ — ใช้ลิงก์นี้แทน
                </h3>
                <p className="text-xs text-rose-700 mb-3">
                  {result.warning ||
                    "SMTP ไม่ตั้งค่า (dev mode) — copy ลิงก์ด้านล่างเปิดในเบราว์เซอร์ทันที"}
                </p>
                <div className="bg-white border border-rose-200 rounded p-3 font-mono text-[11px] break-all text-rose-900 mb-3">
                  {result.secret_retrieval_url}
                </div>
                <a
                  href={result.secret_retrieval_url}
                  target="_blank"
                  rel="noopener"
                  className="inline-block px-4 py-2 rounded-lg bg-rose-600 hover:bg-rose-700 text-white text-sm font-semibold"
                >
                  เปิดลิงก์ในแท็บใหม่ →
                </a>
              </div>
            )}

            {result.webhook_endpoints && (
              <div className="rounded-lg bg-ink-50 border border-ink-200 p-5 mb-6">
                <div className="text-xl mb-1">🔔</div>
                <h3 className="font-bold text-ink-900 mb-1">
                  Webhook Endpoints (สร้างบนเซิร์ฟเวอร์ของคุณ)
                </h3>
                <p className="text-xs text-ink-600 mb-3">
                  Hub จะ POST event มาที่ URL เหล่านี้ — สร้าง receiver + verify
                  HMAC ด้วย <code className="font-mono">WEBHOOK_SHARED_KEY</code>
                </p>
                <div className="space-y-2">
                  <div>
                    <div className="text-[10px] font-bold uppercase tracking-wider text-ink-500 mb-0.5">
                      ถอดสิทธิ์ (access_revoked)
                    </div>
                    <div className="bg-white border border-ink-200 rounded px-2 py-1.5 font-mono text-[11px] break-all text-ink-800">
                      {result.webhook_endpoints.access_revoked}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] font-bold uppercase tracking-wider text-ink-500 mb-0.5">
                      เปลี่ยน role/scope (access_updated)
                    </div>
                    <div className="bg-white border border-ink-200 rounded px-2 py-1.5 font-mono text-[11px] break-all text-ink-800">
                      {result.webhook_endpoints.access_updated}
                    </div>
                  </div>
                </div>
                {result.webhook_note && (
                  <p className="text-[11px] text-ink-500 mt-3 leading-relaxed">
                    💡 {result.webhook_note}
                  </p>
                )}
              </div>
            )}

            <div className="flex gap-3">
              <Link
                href={`/developer/subsystems/${result.subsystem_id}`}
                className="flex-1 px-4 py-2.5 rounded-lg bg-brand-600 hover:bg-brand-700 text-white text-sm font-semibold text-center transition"
              >
                ไปยังหน้าระบบ →
              </Link>
              <button
                onClick={() => router.push("/developer/subsystems")}
                className="px-4 py-2.5 rounded-lg border border-ink-200 hover:bg-ink-50 text-sm font-medium text-ink-700 transition"
              >
                กลับรายการ
              </button>
            </div>
          </div>
        </main>
      </>
    );
  }

  // ── Registration form ────────────────────────────────────
  return (
    <>
      <Topbar title="ลงทะเบียนระบบย่อย" />
      <main className="p-8 max-w-3xl mx-auto w-full">
        <div className="mb-6">
          <Link
            href="/developer/subsystems"
            className="text-xs text-ink-500 hover:text-brand-600 underline"
          >
            ← กลับไป Developer Portal
          </Link>
        </div>

        {error && (
          <div className="mb-5 p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm">
            {error}
          </div>
        )}

        {verifying && (
          <div className="mb-5 p-4 rounded-lg bg-brand-50 border border-brand-200 text-brand-700 text-sm flex items-center gap-2">
            <span className="animate-pulse">🔐</span>
            กำลังยืนยันด้วย Passkey… ทำตามที่อุปกรณ์แจ้ง (ข้อมูลในฟอร์มยังอยู่ครบ)
          </div>
        )}

        <form
          onSubmit={submit}
          className="bg-white rounded-xl border border-ink-200 shadow-sm p-6 space-y-6"
        >
          {/* Name */}
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-ink-500 mb-2">
              ชื่อระบบ <span className="text-rose-500">*</span>
            </label>
            <input
              type="text"
              required
              placeholder="เช่น ระบบหอพัก คณะวิทยาศาสตร์"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-ink-200 focus:outline-none focus:border-brand-500 text-sm"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-ink-500 mb-2">
              คำอธิบาย
            </label>
            <textarea
              rows={3}
              placeholder="ระบบจองห้องสำหรับนักศึกษาหอใน — รองรับ OAuth login ผ่าน Hub"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-ink-200 focus:outline-none focus:border-brand-500 text-sm"
            />
          </div>

          {/* Redirect URIs */}
          <div>
            <div className="flex items-baseline justify-between mb-2">
              <label className="text-xs font-bold uppercase tracking-wider text-ink-500">
                Redirect URIs <span className="text-rose-500">*</span>
              </label>
              <button
                type="button"
                onClick={addUri}
                className="text-xs text-brand-600 hover:text-brand-700 font-semibold"
              >
                + เพิ่ม URI
              </button>
            </div>
            <p className="text-[11px] text-ink-500 mb-3">
              URL ที่ Hub จะ redirect กลับหลัง user login สำเร็จ — ต้องตรงกับที่
              subsystem ใช้จริง (กัน open redirect)
            </p>
            <div className="space-y-2">
              {redirectUris.map((u, i) => (
                <div key={i} className="flex gap-2">
                  <input
                    type="url"
                    placeholder="http://localhost:8001/oauth/callback"
                    value={u}
                    onChange={(e) => setUri(i, e.target.value)}
                    className="flex-1 px-3 py-2 rounded-lg border border-ink-200 focus:outline-none focus:border-brand-500 font-mono text-xs"
                  />
                  {redirectUris.length > 1 && (
                    <button
                      type="button"
                      onClick={() => removeUri(i)}
                      className="px-3 py-2 rounded-lg bg-rose-50 hover:bg-rose-100 text-rose-700 text-sm border border-rose-200"
                      title="ลบ URI นี้"
                    >
                      ✕
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Scope */}
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-ink-500 mb-2">
              Scope ที่ต้องการ <span className="text-rose-500">*</span>
            </label>
            <p className="text-[11px] text-ink-500 mb-3">
              เลือกเฉพาะข้อมูลที่ระบบของคุณจำเป็นต้องใช้ — Hub จะใส่เฉพาะ field
              นี้ใน JWT (data minimization)
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {SCOPE_OPTIONS.map((s) => {
                const checked = scope.has(s.key);
                return (
                  <label
                    key={s.key}
                    className={
                      "flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition " +
                      (checked
                        ? "bg-brand-50 border-brand-300"
                        : "bg-white border-ink-200 hover:border-brand-200")
                    }
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleScope(s.key)}
                      className="mt-0.5 accent-brand-600"
                    />
                    <div className="flex-1">
                      <div className="text-sm font-semibold text-ink-900">
                        {s.label}{" "}
                        <span className="font-mono text-[10px] text-ink-400">
                          {s.key}
                        </span>
                      </div>
                      <div className="text-[11px] text-ink-500 mt-0.5">
                        {s.desc}
                      </div>
                    </div>
                  </label>
                );
              })}
            </div>
          </div>

          {/* Access Policy */}
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-ink-500 mb-2">
              นโยบายการเข้าถึง (Access Policy) <span className="text-rose-500">*</span>
            </label>
            <p className="text-[11px] text-ink-500 mb-3">
              ใครเข้าใช้ระบบนี้ได้ — ตรวจตอน login + ใช้กับ Roster API
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-3">
              {POLICY_OPTIONS.map((p) => (
                <button
                  key={p.key}
                  type="button"
                  onClick={() => setAccessPolicy(p.key)}
                  className={
                    "flex items-start gap-2.5 p-3 rounded-lg border-2 text-left transition " +
                    (accessPolicy === p.key
                      ? "bg-brand-50 border-brand-400"
                      : "bg-white border-ink-200 hover:border-brand-200")
                  }
                >
                  <span className="text-xl leading-none">{p.icon}</span>
                  <div className="min-w-0">
                    <div className="text-sm font-bold text-ink-900">{p.label}</div>
                    <div className="text-[11px] text-ink-500 mt-0.5 leading-snug">{p.desc}</div>
                  </div>
                </button>
              ))}
            </div>

            {accessPolicy === "role" && (
              <div className="p-3 rounded-lg bg-ink-50 border border-ink-100">
                <div className="text-[11px] font-bold text-ink-500 uppercase tracking-wider mb-2">เลือกบทบาทที่เข้าได้</div>
                <div className="flex flex-wrap gap-2">
                  {USER_TYPES.map((r) => (
                    <button
                      key={r}
                      type="button"
                      onClick={() =>
                        setPolicyRoles((cur) => {
                          const n = new Set(cur);
                          n.has(r) ? n.delete(r) : n.add(r);
                          return n;
                        })
                      }
                      className={
                        "px-3 py-1.5 rounded-full text-xs font-semibold border transition " +
                        (policyRoles.has(r)
                          ? "bg-emerald-100 border-emerald-300 text-emerald-800"
                          : "bg-white border-ink-200 text-ink-500 hover:border-ink-300")
                      }
                    >
                      {policyRoles.has(r) ? "✓ " : ""}{r}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {accessPolicy === "attribute" && (
              <div className="p-3 rounded-lg bg-ink-50 border border-ink-100 space-y-2">
                <input
                  type="text"
                  placeholder="คณะ (faculty) — คั่นด้วย , เช่น วิศวกรรมศาสตร์, แพทยศาสตร์"
                  value={policyFaculty}
                  onChange={(e) => setPolicyFaculty(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-ink-200 focus:outline-none focus:border-brand-500 text-sm"
                />
                <input
                  type="text"
                  placeholder="สาขา (major) — คั่นด้วย , เช่น คอมพิวเตอร์, จิตเวช"
                  value={policyMajor}
                  onChange={(e) => setPolicyMajor(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-ink-200 focus:outline-none focus:border-brand-500 text-sm"
                />
              </div>
            )}

            {accessPolicy === "explicit" && (
              <p className="text-[11px] text-ink-500">เพิ่มรายชื่อทีหลังในหน้าจัดการ subsystem (เพิ่มทีละคน / CSV)</p>
            )}
            {accessPolicy === "all" && (
              <p className="text-[11px] text-amber-700">⚠️ ผู้ใช้ทุกคนที่ active เข้าได้</p>
            )}
          </div>

          {/* Webhook URL (optional) */}
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-ink-500 mb-2">
              Access-revoke Webhook URL{" "}
              <span className="text-ink-400 normal-case">(optional)</span>
            </label>
            <p className="text-[11px] text-ink-500 mb-3">
              URL ที่ Hub จะ POST แจ้งเตือนเมื่อมี user ถูก revoke ออกจาก whitelist
              <br />
              ปล่อยว่าง = Hub จะใช้{" "}
              <code className="bg-ink-100 px-1 rounded">
                {`{origin ของ redirect_uri[0]}/internal/access-revoked`}
              </code>
            </p>
            <input
              type="url"
              placeholder="(ปล่อยว่างได้)"
              value={webhookUrl}
              onChange={(e) => setWebhookUrl(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-ink-200 focus:outline-none focus:border-brand-500 font-mono text-[12px]"
            />
          </div>

          {/* Submit */}
          <div className="flex items-center justify-between pt-4 border-t border-ink-100">
            <p className="text-[11px] text-ink-500 max-w-sm">
              หลังกดลงทะเบียน — Hub จะส่ง <strong>client_secret</strong> ทางอีเมล
              ของคุณ (ใช้ได้ครั้งเดียว 15 นาที)
            </p>
            <button
              type="submit"
              disabled={busy}
              className="px-6 py-2.5 rounded-lg bg-brand-600 hover:bg-brand-700 text-white text-sm font-semibold disabled:opacity-50 transition shadow-sm"
            >
              {verifying
                ? "กำลังยืนยัน…"
                : busy
                  ? "กำลังลงทะเบียน…"
                  : "ลงทะเบียน →"}
            </button>
          </div>
        </form>
      </main>
    </>
  );
}
