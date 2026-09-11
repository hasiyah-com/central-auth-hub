"use client";

/**
 * PasskeyCard — แถวอุปกรณ์ Passkey หนึ่งตัว + เปลี่ยนชื่อ/ลบแบบ inline (Phase 3).
 *
 * สไตล์ใช้ cx-pk-* (signal-console.css) ให้เข้าชุดกับ panel อื่นในหน้า /account
 * — ต้องอยู่ใต้ `.sc` ซึ่ง AccountView ครอบให้แล้ว
 *
 * ไอคอนเป็น inline SVG: ของเดิมใช้ emoji แล้วถูกตัดออกตามกฎโปรเจกต์
 * เหลือปุ่มเปล่า กดได้แต่มองไม่เห็น
 */

import { useState } from "react";
import { deletePasskey, renamePasskey, type PasskeyInfo } from "@/lib/passkey";

function relTime(iso: string | null): string {
  if (!iso) return "ยังไม่เคยใช้";
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const min = Math.floor(diff / 60000);
  if (min < 1) return "เมื่อสักครู่";
  if (min < 60) return `${min} นาทีที่แล้ว`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} ชม.ที่แล้ว`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day} วันที่แล้ว`;
  return d.toLocaleDateString("th-TH");
}

/** อุปกรณ์ในเครื่อง (Touch ID / Windows Hello) */
const IconDevice = () => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <rect x="5" y="2" width="14" height="20" rx="2" />
    <path d="M12 18h.01" />
  </svg>
);

/** กุญแจฮาร์ดแวร์ภายนอก (YubiKey ฯลฯ) */
const IconKey = () => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <circle cx="7.5" cy="15.5" r="4.5" />
    <path d="m10.7 12.3 8.3-8.3" />
    <path d="m17 5 3 3" />
    <path d="m14 8 3 3" />
  </svg>
);

const IconPencil = () => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M12 20h9" />
    <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z" />
  </svg>
);

const IconTrash = () => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M3 6h18" />
    <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
    <path d="M19 6v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6" />
    <path d="M10 11v6M14 11v6" />
  </svg>
);

type Props = {
  pk: PasskeyInfo;
  isLast: boolean;
  onChanged: () => void;
};

export function PasskeyCard({ pk, isLast, onChanged }: Props) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(pk.device_name);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isPlatform = pk.device_type === "platform";

  const save = async () => {
    if (!name.trim() || name.trim() === pk.device_name) {
      setEditing(false);
      setName(pk.device_name);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await renamePasskey(pk.id, name.trim());
      setEditing(false);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "เปลี่ยนชื่อไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await deletePasskey(pk.id);
      onChanged();
    } catch (e) {
      const msg =
        typeof e === "object" && e && "detail" in e
          ? typeof (e as { detail: unknown }).detail === "object"
            ? "ลบ Passkey ตัวสุดท้ายไม่ได้ — ต้องเหลืออย่างน้อย 1 ตัว"
            : String((e as { detail: unknown }).detail)
          : e instanceof Error
            ? e.message
            : "ลบไม่สำเร็จ";
      setError(msg);
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  };

  const cancelEdit = () => {
    setEditing(false);
    setName(pk.device_name);
  };

  return (
    <div className="cx-pk-row">
      <i className={isPlatform ? undefined : "roaming"}>
        {isPlatform ? <IconDevice /> : <IconKey />}
      </i>

      <div>
        {editing ? (
          <div className="cx-pk-rename">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              maxLength={100}
              disabled={busy}
              aria-label="ชื่ออุปกรณ์"
              onKeyDown={(e) => {
                if (e.key === "Enter") save();
                if (e.key === "Escape") cancelEdit();
              }}
            />
            <button
              type="button"
              className="cx-primary"
              onClick={save}
              disabled={busy}
            >
              บันทึก
            </button>
            <button type="button" onClick={cancelEdit} disabled={busy}>
              ยกเลิก
            </button>
          </div>
        ) : (
          <>
            <div className="cx-pk-name">
              <b>{pk.device_name}</b>
              <span className="cx-chip">
                {isPlatform ? "platform" : "security key"}
              </span>
            </div>
            <div className="cx-pk-meta">
              ใช้ล่าสุด {relTime(pk.last_used_at)}
              {pk.last_used_country ? ` · ${pk.last_used_country}` : ""}
              {pk.counter_regression_count > 0 && (
                <span className="warn">
                  {" "}
                  · counter regression {pk.counter_regression_count}
                </span>
              )}
            </div>
            {error && <div className="cx-pk-error">{error}</div>}
          </>
        )}
      </div>

      {!editing && (
        <div className="cx-pk-actions">
          {confirming ? (
            <div className="cx-pk-confirm">
              <span>ลบอุปกรณ์นี้?</span>
              <button
                type="button"
                className="danger"
                onClick={remove}
                disabled={busy}
              >
                ลบ
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                disabled={busy}
              >
                ไม่
              </button>
            </div>
          ) : (
            <>
              <button
                type="button"
                className="cx-pk-icon"
                onClick={() => setEditing(true)}
                title="เปลี่ยนชื่อ"
                aria-label="เปลี่ยนชื่ออุปกรณ์"
              >
                <IconPencil />
              </button>
              <button
                type="button"
                className="cx-pk-icon danger"
                onClick={() => setConfirming(true)}
                disabled={isLast}
                title={isLast ? "ลบตัวสุดท้ายไม่ได้ — ต้องเหลืออย่างน้อย 1 ตัว" : "ลบ"}
                aria-label="ลบอุปกรณ์"
              >
                <IconTrash />
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
