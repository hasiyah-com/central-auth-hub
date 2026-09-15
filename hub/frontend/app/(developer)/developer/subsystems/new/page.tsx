"use client";

/**
 * ลงทะเบียนระบบย่อย (OAuth client registration).
 *
 * โครงหน้า/สไตล์ port จากดีไซน์ Signal Console (cx-register-* ใน signal-console.css)
 * ตรรกะเดิมคงไว้ครบ: inline step-up ด้วย Passkey (ข้อมูลในฟอร์มไม่หาย),
 * scope 10 ตัวตาม ALLOWED_SCOPES ของ backend, access policy 4 แบบ,
 * redirect URI หลายตัว, webhook URL
 *
 * ต่างจากดีไซน์ต้นแบบ 3 จุด (ดีไซน์เป็น mockup ไม่ได้ผูกกับ backend จริง):
 *   - "บทบาทที่อนุญาต" ในดีไซน์เป็น input ข้อความ → ของจริงเป็น access policy
 *     4 แบบ (explicit/all/role/attribute) เพราะ backend ตรวจตาม policy นี้
 *   - scope 3 ตัวในดีไซน์ (profile/email/roles) → ของจริงมี 10 ตัว
 *   - เพิ่มหน้าผลลัพธ์หลังส่งคำขอ (client_id / API key / ลิงก์รับ secret)
 *     ซึ่งดีไซน์ไม่มี แต่จำเป็นเพราะค่าพวกนี้แสดงครั้งเดียว
 *
 * แถบ progress 01-03 เดินตาม state จริงของฟอร์ม ไม่ใช่ค่าคงที่
 */

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";
import { mutateWithStepup } from "@/lib/passkey";
import "@/app/signal-room.css";
import "@/app/signal-console.css";

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

const POLICY_OPTIONS: Array<{ key: string; label: string; desc: string }> = [
  { key: "explicit", label: "Whitelist", desc: "เฉพาะรายชื่อที่เพิ่มเอง / อัปโหลด CSV" },
  { key: "all", label: "All Users", desc: "ผู้ใช้ทุกคนที่สถานะ active เข้าได้" },
  { key: "role", label: "Role", desc: "เฉพาะบทบาทที่เลือก" },
  { key: "attribute", label: "Attribute", desc: "เฉพาะคณะ / สาขาที่ระบุ" },
];

const USER_TYPES = ["student", "teacher", "staff", "admin"];

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

type Me = { email: string; full_name: string | null; user_type: string | null };

/* ── ไอคอนเส้น (โปรเจกต์ไม่ได้ติดตั้ง lucide) ─────────────────────────── */

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

const IconBoxes = () => (
  <Icon>
    <path d="M2.97 12.92A2 2 0 0 0 2 14.63v3.24a2 2 0 0 0 .97 1.71l3 1.8a2 2 0 0 0 2.06 0L12 19v-5.5l-5-3-4.03 2.42Z" />
    <path d="m7 16.5-4.74-2.85" />
    <path d="M12 13.5V19l3.97 2.38a2 2 0 0 0 2.06 0l3-1.8a2 2 0 0 0 .97-1.71v-3.24a2 2 0 0 0-.97-1.71L17 10.5l-5 3Z" />
    <path d="m17 16.5 4.74-2.85" />
    <path d="M7.97 4.42A2 2 0 0 0 7 6.13v4.37l5 3 5-3V6.13a2 2 0 0 0-.97-1.71l-3-1.8a2 2 0 0 0-2.06 0l-3 1.8Z" />
    <path d="M12 8 7.26 5.15" />
    <path d="m12 8 4.74-2.85" />
  </Icon>
);
const IconGlobe = () => (
  <Icon>
    <circle cx="12" cy="12" r="10" />
    <path d="M2 12h20" />
    <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
  </Icon>
);
const IconShieldCheck = ({ size = 16 }: { size?: number }) => (
  <Icon size={size}>
    <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67 0C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" />
    <path d="m9 12 2 2 4-4" />
  </Icon>
);
const IconCheck = ({ size = 14 }: { size?: number }) => (
  <Icon size={size}>
    <path d="M20 6 9 17l-5-5" />
  </Icon>
);
const IconCheckCircle = ({ size = 17 }: { size?: number }) => (
  <Icon size={size}>
    <path d="M21.8 10A10 10 0 1 1 17 3.34" />
    <path d="m9 11 3 3L22 4" />
  </Icon>
);
const IconKey = () => (
  <Icon size={19}>
    <circle cx="7.5" cy="15.5" r="4.5" />
    <path d="m10.7 12.3 8.3-8.3" />
    <path d="m17 5 3 3" />
    <path d="m14 8 3 3" />
  </Icon>
);
const IconChevron = ({ size = 16 }: { size?: number }) => (
  <Icon size={size}>
    <path d="m9 18 6-6-6-6" />
  </Icon>
);
const IconPlus = () => (
  <Icon size={13}>
    <path d="M5 12h14M12 5v14" />
  </Icon>
);
const IconX = () => (
  <Icon size={13}>
    <path d="M18 6 6 18M6 6l12 12" />
  </Icon>
);

export default function NewSubsystemPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
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

  useEffect(() => {
    clientFetch<Me>("/auth/me")
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

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

  // ── สถานะความพร้อม — ใช้ทั้งแถบ progress, สรุปคำขอ และเช็กลิสต์ ──
  const hasName = name.trim().length > 0;
  const cleanUris = redirectUris.map((u) => u.trim()).filter(Boolean);
  const hasUri = cleanUris.length > 0;
  const hasScope = scope.size > 0;
  const policyReady =
    accessPolicy === "explicit" ||
    accessPolicy === "all" ||
    (accessPolicy === "role" && policyRoles.size > 0) ||
    (accessPolicy === "attribute" &&
      (policyFaculty.trim().length > 0 || policyMajor.trim().length > 0));
  const ready = hasName && hasUri && hasScope && policyReady;
  // 01 = ยังไม่กรอกชื่อ, 02 = กรอกชื่อแล้วกำลังตั้งค่า OAuth, 03 = ครบพร้อมส่ง
  const step = !hasName ? 1 : ready ? 3 : 2;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!hasUri) {
      setError("ต้องมี redirect URI อย่างน้อย 1 ตัว");
      return;
    }
    if (!hasScope) {
      setError("ต้องเลือก scope อย่างน้อย 1 ตัว");
      return;
    }

    // สร้าง access_policy_config ตาม policy ที่เลือก
    const splitList = (s: string) =>
      s
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean);
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

  /* ── หน้าผลลัพธ์ ─────────────────────────────────────────────── */
  if (result) {
    const viaEmail = result.secret_delivery === "email"; // pragma: allowlist secret
    return (
      <div className="sc">
        <Topbar title="ลงทะเบียนสำเร็จ" />
        <div className="cx-document">
          <section className="cx-done-hero">
            <i>
              <IconCheckCircle size={22} />
            </i>
            <div>
              <span>registration submitted</span>
              <h2>ลงทะเบียนเรียบร้อย</h2>
              <p>ระบบเข้าสู่สถานะ รออนุมัติ จาก Hub Admin</p>
            </div>
          </section>

          <section className="cx-done-ids">
            <div>
              <small>Client ID</small>
              <code>{result.client_id}</code>
            </div>
            <div>
              <small>Subsystem ID</small>
              <code>{result.subsystem_id}</code>
            </div>
          </section>

          <section className="cx-register-layout" style={{ marginTop: 10 }}>
            <div style={{ display: "grid", gap: 10, alignContent: "start" }}>
              {result.api_key && (
                <article className="cx-panel">
                  <header>
                    <div>
                      <span className="mono">roster api key</span>
                      <h2>คีย์สำหรับดึงรายชื่อผู้ใช้</h2>
                    </div>
                    <span className="cx-chip warn">แสดงครั้งเดียว</span>
                  </header>
                  <p className="cx-note">
                    {result.api_key_note ||
                      "ใช้ดึงรายชื่อผู้ใช้ผ่าน GET /api/v1/roster"}
                  </p>
                  <div className="cx-reveal">{result.api_key}</div>
                </article>
              )}

              <article className="cx-panel">
                <header>
                  <div>
                    <span className="mono">client secret</span>
                    <h2>
                      {viaEmail
                        ? "ส่งลิงก์รับ Secret ทางอีเมลแล้ว"
                        : "ส่งอีเมลไม่สำเร็จ — ใช้ลิงก์นี้แทน"}
                    </h2>
                  </div>
                  <span className={viaEmail ? "cx-chip signal" : "cx-chip danger"}>
                    {viaEmail ? "EMAIL" : "FALLBACK"}
                  </span>
                </header>

                {viaEmail ? (
                  <>
                    <p className="cx-note">
                      ส่งไปที่ <code>{result.secret_sent_to}</code>
                    </p>
                    <div className="cx-setting-row">
                      <div>
                        <b>ลิงก์หมดอายุใน 15 นาที และเปิดได้ครั้งเดียว</b>
                        <small>
                          ตรวจทั้ง inbox และ spam · คัดลอก secret ใส่ .env ทันที ·
                          ถ้าพลาดต้องลงทะเบียนระบบใหม่ทั้งหมด
                        </small>
                      </div>
                    </div>
                  </>
                ) : (
                  <>
                    <p className="cx-note">
                      {result.warning ||
                        "SMTP ไม่ได้ตั้งค่า (dev mode) — เปิดลิงก์ด้านล่างทันที"}
                    </p>
                    <div className="cx-reveal">{result.secret_retrieval_url}</div>
                    <div className="cx-panel-foot">
                      <a
                        className="cx-panel-action"
                        href={result.secret_retrieval_url}
                        target="_blank"
                        rel="noopener"
                      >
                        เปิดลิงก์ในแท็บใหม่
                        <IconChevron size={13} />
                      </a>
                    </div>
                  </>
                )}
              </article>

              {result.webhook_endpoints && (
                <article className="cx-panel">
                  <header>
                    <div>
                      <span className="mono">webhook endpoints</span>
                      <h2>ปลายทางที่ต้องสร้างบนเซิร์ฟเวอร์ของคุณ</h2>
                    </div>
                  </header>
                  <p className="cx-note">
                    Hub จะ POST event มาที่ URL เหล่านี้ — สร้าง receiver แล้ว verify
                    HMAC ด้วย <code>WEBHOOK_SHARED_KEY</code>
                  </p>
                  <div className="cx-reveal">
                    access_revoked · {result.webhook_endpoints.access_revoked}
                  </div>
                  <div className="cx-reveal">
                    access_updated · {result.webhook_endpoints.access_updated}
                  </div>
                  {result.webhook_note && (
                    <p className="cx-note">{result.webhook_note}</p>
                  )}
                </article>
              )}

              <div className="cx-done-actions">
                <Link
                  className="primary"
                  href={`/developer/subsystems/${result.subsystem_id}`}
                >
                  ไปยังหน้าระบบ
                  <IconChevron size={14} />
                </Link>
                <a
                  href="#"
                  onClick={(e) => {
                    e.preventDefault();
                    router.push("/developer/subsystems");
                  }}
                >
                  กลับรายการ
                </a>
              </div>
            </div>

            <aside className="cx-register-side">
              <article className="cx-register-summary">
                <header>
                  <span className="mono">next steps</span>
                  <h2>ขั้นตอนถัดไป</h2>
                </header>
                <div className="cx-secret-warning">
                  <IconKey />
                  <div>
                    <b>เก็บ Secret ทันที</b>
                    <p>
                      Client Secret และ API Key แสดงเพียงครั้งเดียว ระบบไม่เก็บ
                      plaintext ไว้ ถ้าทำหาย ต้องออกใหม่หรือลงทะเบียนใหม่
                    </p>
                  </div>
                </div>
                <dl>
                  <div>
                    <dt>สถานะ</dt>
                    <dd>
                      <span className="cx-dot warn" />
                      {result.status.toUpperCase()}
                    </dd>
                  </div>
                  <div>
                    <dt>Scopes</dt>
                    <dd className="mono">
                      {String(scope.size).padStart(2, "0")} SELECTED
                    </dd>
                  </div>
                  <div>
                    <dt>Redirect URIs</dt>
                    <dd className="mono">
                      {String(cleanUris.length).padStart(2, "0")}
                    </dd>
                  </div>
                </dl>
              </article>
            </aside>
          </section>
        </div>
      </div>
    );
  }

  /* ── ฟอร์มลงทะเบียน ──────────────────────────────────────────── */
  return (
    <div className="sc">
      <Topbar title="ลงทะเบียนระบบย่อย" />

      <div className="cx-document">
        <section className="cx-register-progress">
          <div className={step === 1 ? "active" : undefined}>
            <span className="mono">01</span>
            <b>ข้อมูลระบบ</b>
            <small>ชื่อและผู้รับผิดชอบ</small>
          </div>
          <IconChevron />
          <div className={step === 2 ? "active" : undefined}>
            <span className="mono">02</span>
            <b>OAuth &amp; Permission</b>
            <small>Endpoint, Scope และนโยบายการเข้าถึง</small>
          </div>
          <IconChevron />
          <div className={step === 3 ? "active" : undefined}>
            <span className="mono">03</span>
            <b>ตรวจสอบคำขอ</b>
            <small>รอผู้ดูแลอนุมัติ</small>
          </div>
        </section>

        <section className="cx-register-layout">
          <form className="cx-panel cx-register-form" onSubmit={submit}>
            <header>
              <div>
                <span className="mono">oauth client registration</span>
                <h2>ลงทะเบียนระบบย่อย</h2>
              </div>
              <span className="cx-chip warn">DRAFT</span>
            </header>

            {error && <div className="cx-inline-error">{error}</div>}
            {verifying && (
              <div className="cx-inline-warn">
                กำลังยืนยันด้วย Passkey — ทำตามที่อุปกรณ์แจ้ง (ข้อมูลในฟอร์มยังอยู่ครบ)
              </div>
            )}

            {/* ── 1. ข้อมูลระบบ ── */}
            <section className="cx-register-section">
              <div className="cx-register-section-head">
                <i>
                  <IconBoxes />
                </i>
                <span>
                  <small className="mono">SYSTEM IDENTITY</small>
                  <h3>ข้อมูลระบบ</h3>
                  <p>ข้อมูลนี้จะแสดงบนหน้าขออนุญาตเข้าใช้งาน</p>
                </span>
              </div>
              <div className="cx-register-fields">
                <div className="cx-register-fields two">
                  <label>
                    <span>
                      ชื่อระบบ <b>*</b>
                    </span>
                    <input
                      type="text"
                      required
                      placeholder="เช่น ระบบหอพัก คณะวิทยาศาสตร์"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                    />
                  </label>
                  <label>
                    <span>ผู้รับผิดชอบ</span>
                    <input
                      type="text"
                      readOnly
                      value={
                        me
                          ? `${me.full_name || me.email}${me.user_type ? ` · ${me.user_type}` : ""}`
                          : ""
                      }
                    />
                  </label>
                </div>
                <label>
                  <span>
                    คำอธิบาย <em>(ไม่บังคับ)</em>
                  </span>
                  <textarea
                    placeholder="ระบบจองห้องสำหรับนักศึกษาหอใน — รองรับ OAuth login ผ่าน Hub"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </label>
              </div>
            </section>

            {/* ── 2. เส้นทางเชื่อมต่อ ── */}
            <section className="cx-register-section">
              <div className="cx-register-section-head">
                <i>
                  <IconGlobe />
                </i>
                <span>
                  <small className="mono">OAUTH ENDPOINTS</small>
                  <h3>เส้นทางเชื่อมต่อ</h3>
                  <p>ระบุ URL ที่ระบบอนุญาตให้รับผลการยืนยันตัวตน</p>
                </span>
              </div>
              <div className="cx-register-fields">
                <label>
                  <span>
                    Redirect URIs <b>*</b>
                  </span>
                  {redirectUris.map((u, i) => (
                    <div
                      key={i}
                      style={{ display: "flex", gap: 7, marginBottom: 7 }}
                    >
                      <input
                        className="mono"
                        type="url"
                        placeholder="http://localhost:8001/oauth/callback"
                        value={u}
                        onChange={(e) => setUri(i, e.target.value)}
                      />
                      {redirectUris.length > 1 && (
                        <button
                          type="button"
                          className="cx-panel-action"
                          onClick={() => removeUri(i)}
                          title="ลบ URI นี้"
                          aria-label="ลบ URI นี้"
                        >
                          <IconX />
                        </button>
                      )}
                    </div>
                  ))}
                  <button
                    type="button"
                    className="cx-panel-action"
                    onClick={addUri}
                  >
                    <IconPlus />
                    เพิ่ม URI
                  </button>
                  <small>
                    URL ที่ Hub จะ redirect กลับหลัง login สำเร็จ ต้องตรงกับที่
                    subsystem ใช้จริง (กัน open redirect)
                  </small>
                </label>
                <label>
                  <span>
                    Access-revoke Webhook URL <em>(ไม่บังคับ)</em>
                  </span>
                  <input
                    className="mono"
                    type="url"
                    placeholder="https://library.uni.ac.th/internal/access-revoked"
                    value={webhookUrl}
                    onChange={(e) => setWebhookUrl(e.target.value)}
                  />
                  <small>
                    URL ที่ Hub จะ POST แจ้งเมื่อมีผู้ใช้ถูกถอนสิทธิ์ ปล่อยว่าง =
                    ใช้ origin ของ redirect_uri ตัวแรก + /internal/access-revoked
                  </small>
                </label>
              </div>
            </section>

            {/* ── 3. ข้อมูลและสิทธิ์ที่ระบบขอใช้ ── */}
            <section className="cx-register-section">
              <div className="cx-register-section-head">
                <i>
                  <IconShieldCheck />
                </i>
                <span>
                  <small className="mono">ACCESS PERMISSION</small>
                  <h3>ข้อมูลที่ระบบขอใช้</h3>
                  <p>เลือกเฉพาะข้อมูลที่จำเป็นต่อการทำงานของระบบ</p>
                </span>
              </div>

              <fieldset className="cx-scope-grid">
                <legend className="sr-only">Scopes</legend>
                {SCOPE_OPTIONS.map((s) => {
                  const checked = scope.has(s.key);
                  return (
                    <label key={s.key} className={checked ? "selected" : undefined}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleScope(s.key)}
                      />
                      <span>
                        <code className="mono">{s.key}</code>
                        <b>{s.label}</b>
                        <small>{s.desc}</small>
                      </span>
                      <IconCheck size={16} />
                    </label>
                  );
                })}
              </fieldset>

              <fieldset className="cx-policy-grid">
                <legend className="sr-only">นโยบายการเข้าถึง</legend>
                {POLICY_OPTIONS.map((p) => (
                  <label
                    key={p.key}
                    className={accessPolicy === p.key ? "selected" : undefined}
                  >
                    <input
                      type="radio"
                      name="access-policy"
                      checked={accessPolicy === p.key}
                      onChange={() => setAccessPolicy(p.key)}
                    />
                    <span>
                      <b>{p.label}</b>
                      <small>{p.desc}</small>
                    </span>
                  </label>
                ))}
              </fieldset>

              {accessPolicy === "role" && (
                <div className="cx-policy-config">
                  <span>เลือกบทบาทที่เข้าได้</span>
                  <div className="cx-role-chips">
                    {USER_TYPES.map((r) => (
                      <button
                        key={r}
                        type="button"
                        className={policyRoles.has(r) ? "on" : undefined}
                        onClick={() =>
                          setPolicyRoles((cur) => {
                            const n = new Set(cur);
                            if (n.has(r)) n.delete(r);
                            else n.add(r);
                            return n;
                          })
                        }
                      >
                        {policyRoles.has(r) && <IconCheck size={12} />}
                        {r}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {accessPolicy === "attribute" && (
                <div className="cx-policy-config">
                  <span>เงื่อนไขคุณสมบัติ</span>
                  <div className="cx-register-fields">
                    <label>
                      <input
                        type="text"
                        placeholder="คณะ — คั่นด้วย , เช่น วิศวกรรมศาสตร์, แพทยศาสตร์"
                        value={policyFaculty}
                        onChange={(e) => setPolicyFaculty(e.target.value)}
                      />
                    </label>
                    <label>
                      <input
                        type="text"
                        placeholder="สาขา — คั่นด้วย , เช่น คอมพิวเตอร์, จิตเวช"
                        value={policyMajor}
                        onChange={(e) => setPolicyMajor(e.target.value)}
                      />
                    </label>
                  </div>
                </div>
              )}

              {accessPolicy === "explicit" && (
                <div className="cx-policy-config">
                  <span>รายชื่อ</span>
                  <p className="cx-policy-note">
                    เพิ่มรายชื่อทีหลังในหน้าจัดการระบบ (ทีละคน หรืออัปโหลด CSV)
                  </p>
                </div>
              )}
              {accessPolicy === "all" && (
                <div className="cx-policy-config">
                  <span>ขอบเขต</span>
                  <p className="cx-policy-note">
                    ผู้ใช้ทุกคนที่สถานะ active เข้าได้ ไม่ต้องทำ whitelist
                  </p>
                </div>
              )}
            </section>

            <footer className="cx-register-form-actions">
              <Link href="/developer/subsystems">ยกเลิก</Link>
              <span>
                หลังส่งคำขอ Hub จะส่งลิงก์รับ client_secret ทางอีเมลของคุณ
                (ใช้ได้ครั้งเดียว 15 นาที)
              </span>
              <button type="submit" disabled={busy}>
                <IconShieldCheck />
                {verifying
                  ? "กำลังยืนยัน"
                  : busy
                    ? "กำลังลงทะเบียน"
                    : "ตรวจสอบและส่งคำขอ"}
              </button>
            </footer>
          </form>

          <aside className="cx-register-side">
            <article className="cx-register-checklist">
              <span className="mono">before submit</span>
              <h3>ตรวจสอบก่อนส่ง</h3>
              <ul>
                <li className={hasName ? undefined : "todo"}>
                  <IconCheck />
                  ตั้งชื่อระบบแล้ว
                </li>
                <li className={hasUri ? undefined : "todo"}>
                  <IconCheck />
                  Redirect URI ตรงกับระบบจริง
                </li>
                <li className={hasScope ? undefined : "todo"}>
                  <IconCheck />
                  ขอเฉพาะ Scope ที่จำเป็น
                </li>
                <li className={policyReady ? undefined : "todo"}>
                  <IconCheck />
                  ตั้งนโยบายการเข้าถึงครบ
                </li>
                <li className={webhookUrl.trim() ? undefined : "todo"}>
                  <IconCheck />
                  Webhook รองรับการตรวจลายเซ็น HMAC
                </li>
              </ul>
            </article>
          </aside>
        </section>
      </div>
    </div>
  );
}
