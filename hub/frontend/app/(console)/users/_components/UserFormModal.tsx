"use client";

/**
 * UserFormModal — สร้าง/แก้ไข user (admin).
 *
 * Mutation เป็น critical action → backend คืน 403 stepup_required →
 * clientFetch interceptor (lib/api.ts) พาไป /auth/passkey/stepup อัตโนมัติ
 * แล้วกลับมาหน้าเดิม. ที่นี่แค่ทำ request + แสดง error อื่น ๆ.
 */

import { useState } from "react";
import { clientFetch } from "@/lib/api";
import { runWithStepup } from "@/lib/passkey";

export type UserRow = {
  id: string;
  email: string;
  full_name: string;
  user_type: string;
  identifier?: string;
  faculty?: string;
  major?: string;
  year_or_position?: string;
  phone?: string;
  status?: string;
};

type Props = {
  mode: "create" | "edit";
  user?: UserRow;
  onClose: () => void;
  onSaved: () => void;
};

const USER_TYPES = [
  { v: "student", label: "นักศึกษา" },
  { v: "teacher", label: "อาจารย์" },
  { v: "staff", label: "เจ้าหน้าที่" },
  { v: "admin", label: "Admin" },
];

// สถานะ deleted/graduated/resigned = ออกจากระบบถาวร — backend เพิกถอนสิทธิ์
// ทุก subsystem ทันที (revoke AccessList + kick session) ตอนเปลี่ยนมา, และ
// restore คืนให้ถ้าเปลี่ยนกลับเป็น active (ดู _cascade_revoke_access ใน users.py)
// ต้องตรงกับ _CASCADE_STATUSES ใน hub/backend/app/routers/users.py
const CASCADE_STATUSES = new Set(["deleted", "graduated", "resigned"]);

const USER_STATUSES = [
  { v: "active", label: "Active — ใช้งานได้" },
  { v: "suspended", label: "Suspended — ถูกระงับ" },
  { v: "graduated", label: "Graduated — จบการศึกษา" },
  { v: "resigned", label: "Resigned — ลาออก" },
  { v: "deleted", label: "Deleted — ลบออกจากระบบ" },
];

export function UserFormModal({ mode, user, onClose, onSaved }: Props) {
  const [form, setForm] = useState({
    email: user?.email ?? "",
    full_name: user?.full_name ?? "",
    user_type: user?.user_type ?? "student",
    identifier: user?.identifier ?? "",
    faculty: user?.faculty ?? "",
    major: user?.major ?? "",
    year_or_position: user?.year_or_position ?? "",
    phone: user?.phone ?? "",
    status: user?.status ?? "active",
  });
  const [saving, setSaving] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit() {
    setError(null);
    if (!form.email || !form.full_name) {
      setError("กรอก email และชื่อ-สกุล");
      return;
    }
    setSaving(true);
    // mutation function — เรียกซ้ำได้ (runWithStepup retry หลัง verify)
    const doSave = () => {
      const body =
        mode === "create"
          ? {
              email: form.email,
              full_name: form.full_name,
              user_type: form.user_type,
              identifier: form.identifier || null,
              faculty: form.faculty || null,
              major: form.major || null,
              year_or_position: form.year_or_position || null,
              phone: form.phone || null,
            }
          : {
              email: form.email,
              full_name: form.full_name,
              user_type: form.user_type,
              identifier: form.identifier || null,
              faculty: form.faculty || null,
              major: form.major || null,
              year_or_position: form.year_or_position || null,
              phone: form.phone || null,
              status: form.status,
            };
      return clientFetch(
        mode === "create" ? "/admin/users/" : `/admin/users/${user!.id}`,
        {
          method: mode === "create" ? "POST" : "PATCH",
          body: JSON.stringify(body),
          stepupMode: "throw", // จัดการ step-up inline (ไม่ redirect — ฟอร์มไม่หาย)
        }
      );
    };
    try {
      // Option C — ถ้า 403 stepup_required → verify Passkey ในหน้า แล้ว retry
      await runWithStepup(doSave, setVerifying);
      onSaved();
    } catch (e) {
      const detail =
        typeof e === "object" && e && "detail" in e
          ? (e as { detail: unknown }).detail
          : "บันทึกไม่สำเร็จ";
      const code =
        typeof detail === "object" && detail
          ? (detail as { code?: string }).code
          : undefined;
      if (code === "no_passkey") {
        setError(
          "ต้องมี Passkey เพื่อยืนยันการกระทำนี้ — ไปตั้งค่าที่หน้า บัญชี/ความปลอดภัย หรือใช้ Account Recovery"
        );
      } else if (e instanceof DOMException && e.name === "NotAllowedError") {
        setError("ยกเลิกการยืนยัน Passkey — ลองอีกครั้ง");
      } else {
        setError(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
    } finally {
      setSaving(false);
      setVerifying(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-2xl bg-white shadow-xl max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-ink-100 flex items-center justify-between">
          <h2 className="text-lg font-bold text-ink-900">
            {mode === "create" ? "เพิ่มผู้ใช้ใหม่" : "แก้ไขผู้ใช้"}
          </h2>
          <button onClick={onClose} className="text-ink-400 hover:text-ink-700 text-xl leading-none">
            ×
          </button>
        </div>

        <div className="px-6 py-5 space-y-4">
          {error && (
            <div className="p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm">
              {error}
            </div>
          )}

          <Field label="Email *">
            <input type="email" value={form.email} onChange={set("email")} className={inputCls} placeholder="user@uni.ac.th" />
          </Field>
          <Field label="ชื่อ-สกุล *">
            <input value={form.full_name} onChange={set("full_name")} className={inputCls} placeholder="ชื่อ นามสกุล" />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="ประเภท">
              <select value={form.user_type} onChange={set("user_type")} className={inputCls}>
                {USER_TYPES.map((t) => (
                  <option key={t.v} value={t.v}>{t.label}</option>
                ))}
              </select>
            </Field>
            <Field label="รหัส (identifier)">
              <input value={form.identifier} onChange={set("identifier")} className={inputCls} placeholder="650001 / S9001" />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="คณะ">
              <input value={form.faculty} onChange={set("faculty")} className={inputCls} />
            </Field>
            <Field label="สาขา / ตำแหน่ง">
              <input value={form.major} onChange={set("major")} className={inputCls} />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="ชั้นปี / ตำแหน่ง">
              <input value={form.year_or_position} onChange={set("year_or_position")} className={inputCls} />
            </Field>
            <Field label="เบอร์โทร">
              <input value={form.phone} onChange={set("phone")} className={inputCls} />
            </Field>
          </div>

          {mode === "edit" && (
            <Field label="สถานะ">
              <select value={form.status} onChange={set("status")} className={inputCls}>
                {USER_STATUSES.map((s) => (
                  <option key={s.v} value={s.v}>{s.label}</option>
                ))}
              </select>
              {CASCADE_STATUSES.has(form.status) &&
                form.status !== (user?.status ?? "active") && (
                  <p className="text-[11px] text-amber-600 mt-1">
                    ⚠ เปลี่ยนเป็นสถานะนี้จะเพิกถอนสิทธิ์เข้า subsystem ทั้งหมดทันที
                    (kick session ที่ค้างอยู่ด้วย)
                  </p>
                )}
              {CASCADE_STATUSES.has(user?.status ?? "active") &&
                form.status === "active" && (
                  <p className="text-[11px] text-emerald-600 mt-1">
                    ✓ เปลี่ยนกลับ active จะคืนสิทธิ์ subsystem ที่เคยถูกเพิกถอนไป
                  </p>
                )}
            </Field>
          )}

          {verifying ? (
            <div className="p-3 rounded-lg bg-brand-50 border border-brand-200 text-brand-700 text-sm flex items-center gap-2">
              <span className="animate-pulse">🔐</span>
              กำลังยืนยันด้วย Passkey… ทำตามที่อุปกรณ์แจ้ง (ข้อมูลในฟอร์มยังอยู่)
            </div>
          ) : (
            <p className="text-xs text-ink-400 pt-1">
              🔐 การบันทึกต้องยืนยันตัวตนด้วย Passkey (step-up) — ยืนยันในหน้านี้เลย ไม่ต้องกรอกใหม่
            </p>
          )}
        </div>

        <div className="px-6 py-4 border-t border-ink-100 flex justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 rounded-lg border border-ink-200 text-ink-600 text-sm hover:bg-ink-50">
            ยกเลิก
          </button>
          <button
            onClick={submit}
            disabled={saving}
            className="px-4 py-2 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
          >
            {verifying
              ? "กำลังยืนยัน…"
              : saving
                ? "กำลังบันทึก…"
                : mode === "create"
                  ? "เพิ่มผู้ใช้"
                  : "บันทึก"}
          </button>
        </div>
      </div>
    </div>
  );
}

const inputCls =
  "w-full px-3 py-2 rounded-lg border border-ink-200 bg-white text-sm focus:outline-none focus:border-brand-500";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-ink-500 mb-1">{label}</span>
      {children}
    </label>
  );
}
