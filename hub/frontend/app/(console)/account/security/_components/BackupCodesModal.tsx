"use client";

/**
 * BackupCodesModal — Mandatory show-once UX (Improvement #3, plan v3).
 *
 * Hard rules enforced by component:
 *   1. No close button (no X, no ESC)
 *   2. Cannot acknowledge until user has either copied OR downloaded
 *   3. Cannot acknowledge until checkbox is ticked
 *   4. Acknowledge calls backend → only then resolves promise / closes
 *
 * If user reloads the page before acknowledging, the codes are gone forever
 * (we only show plaintext at generation time — backend stores Argon2id hash).
 * Backend `backup_codes_must_acknowledge` flag stays true until ack is recorded.
 */

import { useEffect, useMemo, useState } from "react";
import { acknowledgeBackupCodes } from "@/lib/passkey";

type Props = {
  codes: string[];
  onAcknowledged: () => void;
};

export function BackupCodesModal({ codes, onAcknowledged }: Props) {
  const [copied, setCopied] = useState(false);
  const [downloaded, setDownloaded] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Block browser back / ESC / X — best effort UX deterrent
  useEffect(() => {
    const beforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue =
        "คุณยังไม่ได้บันทึก backup codes — ออกจากหน้านี้แล้วจะเข้าระบบไม่ได้ถ้าทำ Passkey หาย";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, []);

  const codesText = useMemo(() => codes.join("\n"), [codes]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(codesText);
      setCopied(true);
    } catch {
      // Fallback: select + execCommand
      const ta = document.createElement("textarea");
      ta.value = codesText;
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        setCopied(true);
      } catch {
        setError("ไม่สามารถ copy ได้ — กรุณาใช้ Download แทน");
      } finally {
        document.body.removeChild(ta);
      }
    }
  };

  const handleDownload = () => {
    const blob = new Blob(
      [
        "Central Auth Hub — Passkey Backup Codes\n",
        `Generated: ${new Date().toISOString()}\n`,
        "Use ONE code per recovery — each code works only once.\n",
        "Store this file in a safe place (password manager, locked safe).\n\n",
        codesText,
        "\n",
      ],
      { type: "text/plain;charset=utf-8" }
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `passkey-backup-codes-${new Date()
      .toISOString()
      .slice(0, 10)}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    setDownloaded(true);
  };

  const canAcknowledge =
    (copied || downloaded) && confirmed && !submitting;

  const handleAcknowledge = async () => {
    if (!canAcknowledge) return;
    setSubmitting(true);
    setError(null);
    try {
      await acknowledgeBackupCodes();
      onAcknowledged();
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "ยืนยันไม่สำเร็จ — กรุณาลองใหม่"
      );
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-2xl max-w-2xl w-full max-h-[95vh] overflow-y-auto">
        <div className="px-6 py-5 border-b border-gray-200">
          <div className="flex items-center gap-3">
            <span className="text-3xl">🔑</span>
            <div>
              <h2 className="text-xl font-bold text-gray-900">
                Backup Codes ของคุณ
              </h2>
              <p className="text-sm text-gray-600 mt-0.5">
                บันทึกครั้งเดียวเท่านั้น — เก็บไว้ในที่ปลอดภัย
              </p>
            </div>
          </div>
        </div>

        <div className="px-6 py-5 space-y-4">
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-900">
            <strong className="font-semibold">⚠️ ใช้กรณีฉุกเฉินเท่านั้น:</strong>{" "}
            ถ้าทำ Passkey หาย (เปลี่ยนมือถือ, อุปกรณ์พัง) ใช้ codes เหล่านี้
            กู้บัญชีได้. แต่ละ code ใช้ได้ครั้งเดียว.
          </div>

          <div className="grid grid-cols-2 gap-2 bg-gray-50 border border-gray-200 rounded-lg p-4 font-mono text-base">
            {codes.map((code, i) => (
              <div
                key={i}
                className="flex items-center gap-2 px-3 py-2 bg-white rounded border border-gray-200"
              >
                <span className="text-gray-400 text-xs w-5">
                  {String(i + 1).padStart(2, "0")}.
                </span>
                <span className="text-gray-900 tracking-wider">{code}</span>
              </div>
            ))}
          </div>

          <div className="flex gap-2">
            <button
              onClick={handleCopy}
              className={`flex-1 py-2.5 px-4 rounded-lg font-medium transition ${
                copied
                  ? "bg-emerald-100 text-emerald-800 border border-emerald-300"
                  : "bg-gray-900 text-white hover:bg-gray-800"
              }`}
            >
              {copied ? "✓ คัดลอกแล้ว" : "📋 คัดลอก"}
            </button>
            <button
              onClick={handleDownload}
              className={`flex-1 py-2.5 px-4 rounded-lg font-medium transition ${
                downloaded
                  ? "bg-emerald-100 text-emerald-800 border border-emerald-300"
                  : "bg-gray-900 text-white hover:bg-gray-800"
              }`}
            >
              {downloaded ? "✓ ดาวน์โหลดแล้ว" : "💾 ดาวน์โหลด (.txt)"}
            </button>
          </div>

          <label
            className={`flex items-start gap-3 p-3 rounded-lg cursor-pointer transition ${
              copied || downloaded
                ? "bg-blue-50 hover:bg-blue-100"
                : "bg-gray-50 cursor-not-allowed opacity-60"
            }`}
          >
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
              disabled={!(copied || downloaded)}
              className="mt-1 w-4 h-4 rounded"
            />
            <span className="text-sm text-gray-700">
              ฉันได้บันทึก backup codes ไว้ในที่ปลอดภัยแล้ว
              และเข้าใจว่าหากทำ Passkey และ codes เหล่านี้หาย
              อาจเข้าสู่ระบบไม่ได้
            </span>
          </label>

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-800">
              {error}
            </div>
          )}
        </div>

        <div className="px-6 py-4 bg-gray-50 border-t border-gray-200 rounded-b-xl">
          <button
            onClick={handleAcknowledge}
            disabled={!canAcknowledge}
            className={`w-full py-3 rounded-lg font-semibold transition ${
              canAcknowledge
                ? "bg-emerald-600 text-white hover:bg-emerald-700"
                : "bg-gray-200 text-gray-400 cursor-not-allowed"
            }`}
          >
            {submitting ? "กำลังบันทึก…" : "ยืนยันว่าบันทึกแล้ว"}
          </button>
          {!copied && !downloaded && (
            <p className="text-xs text-gray-500 mt-2 text-center">
              กรุณาคัดลอกหรือดาวน์โหลด codes ก่อน
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
