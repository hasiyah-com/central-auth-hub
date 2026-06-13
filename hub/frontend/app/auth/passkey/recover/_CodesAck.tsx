"use client";

/**
 * CodesAck — แสดง backup codes ใหม่ + copy/download + checkbox + ยืนยัน.
 * เหมือนหน้าได้ codes ครั้งแรก. กดยืนยัน → onConfirm (กลับ login).
 */

import { useMemo, useState } from "react";

export function CodesAck({
  codes,
  onConfirm,
  note,
}: {
  codes: string[];
  onConfirm: () => void;
  note?: string;
}) {
  const [copied, setCopied] = useState(false);
  const [downloaded, setDownloaded] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const text = useMemo(() => codes.join("\n"), [codes]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      /* ignore */
    }
    setCopied(true);
  };
  const download = () => {
    const blob = new Blob(
      [`Central Auth Hub — Backup Codes\n${new Date().toISOString()}\n\n${text}\n`],
      { type: "text/plain" }
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "passkey-backup-codes.txt";
    a.click();
    URL.revokeObjectURL(url);
    setDownloaded(true);
  };

  const canConfirm = (copied || downloaded) && confirmed;

  return (
    <div className="space-y-4">
      <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-900">
        ⚠️ {note || "บันทึก backup codes เหล่านี้ — แสดงครั้งเดียว"}
      </div>

      <div className="grid grid-cols-2 gap-2">
        {codes.map((c, i) => (
          <code
            key={i}
            className="text-sm bg-gray-50 border border-gray-200 rounded px-2 py-1.5 text-center font-mono tracking-wider text-ink-800"
          >
            {c}
          </code>
        ))}
      </div>

      <div className="flex gap-2">
        <button
          onClick={copy}
          className={`flex-1 py-2 rounded-lg text-sm font-medium ${
            copied
              ? "bg-emerald-100 text-emerald-800 border border-emerald-300"
              : "bg-ink-900 text-white hover:bg-ink-800"
          }`}
        >
          {copied ? "✓ คัดลอกแล้ว" : "📋 คัดลอก"}
        </button>
        <button
          onClick={download}
          className={`flex-1 py-2 rounded-lg text-sm font-medium ${
            downloaded
              ? "bg-emerald-100 text-emerald-800 border border-emerald-300"
              : "bg-ink-900 text-white hover:bg-ink-800"
          }`}
        >
          {downloaded ? "✓ ดาวน์โหลดแล้ว" : "💾 ดาวน์โหลด"}
        </button>
      </div>

      <label
        className={`flex items-start gap-2.5 p-2.5 rounded-lg text-sm ${
          copied || downloaded
            ? "bg-blue-50 cursor-pointer"
            : "bg-gray-50 opacity-60 cursor-not-allowed"
        }`}
      >
        <input
          type="checkbox"
          checked={confirmed}
          disabled={!(copied || downloaded)}
          onChange={(e) => setConfirmed(e.target.checked)}
          className="mt-0.5"
        />
        <span className="text-ink-700">
          ฉันบันทึก backup codes ไว้ในที่ปลอดภัยแล้ว
        </span>
      </label>

      <button
        onClick={onConfirm}
        disabled={!canConfirm}
        className={`w-full py-2.5 rounded-lg font-semibold ${
          canConfirm
            ? "bg-emerald-600 text-white hover:bg-emerald-700"
            : "bg-gray-200 text-gray-400 cursor-not-allowed"
        }`}
      >
        ยืนยันและไปหน้า Login
      </button>
      {!copied && !downloaded && (
        <p className="text-xs text-gray-400 text-center">
          คัดลอกหรือดาวน์โหลดก่อน
        </p>
      )}
    </div>
  );
}
