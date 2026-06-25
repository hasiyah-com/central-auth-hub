"use client";

/**
 * PasskeyCard — one passkey row with inline rename + delete confirm (Phase 3).
 */

import { useState } from "react";
import {
  deletePasskey,
  renamePasskey,
  type PasskeyInfo,
} from "@/lib/passkey";

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

  return (
    <div className="flex items-center gap-4 px-4 py-3 rounded-xl border border-gray-200 bg-white">
      <div
        className={`w-10 h-10 rounded-lg grid place-items-center text-lg flex-none ${
          isPlatform
            ? "bg-emerald-50 text-emerald-600"
            : "bg-blue-50 text-blue-600"
        }`}
      >
        {isPlatform ? "💻" : "🔑"}
      </div>

      <div className="flex-1 min-w-0">
        {editing ? (
          <div className="flex items-center gap-2">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              maxLength={100}
              disabled={busy}
              onKeyDown={(e) => {
                if (e.key === "Enter") save();
                if (e.key === "Escape") {
                  setEditing(false);
                  setName(pk.device_name);
                }
              }}
              className="px-2 py-1 border border-emerald-300 rounded text-sm w-48 focus:ring-2 focus:ring-emerald-500"
            />
            <button
              onClick={save}
              disabled={busy}
              className="text-emerald-600 text-sm font-medium hover:text-emerald-700"
            >
              บันทึก
            </button>
            <button
              onClick={() => {
                setEditing(false);
                setName(pk.device_name);
              }}
              disabled={busy}
              className="text-gray-400 text-sm hover:text-gray-600"
            >
              ยกเลิก
            </button>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <span className="font-medium text-gray-900 truncate">
                {pk.device_name}
              </span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">
                {isPlatform ? "platform" : "security key"}
              </span>
            </div>
            <div className="text-xs text-gray-500 mt-0.5">
              ใช้ล่าสุด {relTime(pk.last_used_at)}
              {pk.last_used_country ? ` · ${pk.last_used_country}` : ""}
              {pk.counter_regression_count > 0 && (
                <span className="text-amber-600">
                  {" "}· ⚠ counter regression {pk.counter_regression_count}
                </span>
              )}
            </div>
            {error && (
              <div className="text-xs text-red-600 mt-1">{error}</div>
            )}
          </>
        )}
      </div>

      {!editing && (
        <div className="flex items-center gap-2 flex-none">
          {confirming ? (
            <>
              <span className="text-xs text-gray-500">แน่ใจ?</span>
              <button
                onClick={remove}
                disabled={busy}
                className="text-red-600 text-sm font-medium hover:text-red-700"
              >
                ลบ
              </button>
              <button
                onClick={() => setConfirming(false)}
                disabled={busy}
                className="text-gray-400 text-sm hover:text-gray-600"
              >
                ไม่
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => setEditing(true)}
                className="text-gray-400 hover:text-gray-700 text-sm"
                title="เปลี่ยนชื่อ"
              >
                ✏️
              </button>
              <button
                onClick={() => {
                  if (isLast) {
                    setError(
                      "ลบ Passkey ตัวสุดท้ายไม่ได้ — ต้องเหลืออย่างน้อย 1 ตัว"
                    );
                    return;
                  }
                  setConfirming(true);
                }}
                className={`text-sm ${
                  isLast
                    ? "text-gray-300 cursor-not-allowed"
                    : "text-gray-400 hover:text-red-600"
                }`}
                title={isLast ? "ลบตัวสุดท้ายไม่ได้" : "ลบ"}
              >
                🗑️
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
