"use client";

/**
 * CodesAck — แสดง backup codes ใหม่ + copy/download + checkbox + ยืนยัน.
 * เหมือนหน้าได้ codes ครั้งแรก. กดยืนยัน → onConfirm (กลับ login).
 */

import { useMemo, useState } from "react";
import styles from "./recovery.module.css";

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
    <div className={styles.codesPanel}>
      <div className={styles.codesHeader}>
        <span>RECOVERY CODES</span>
        <h3>บันทึกรหัสสำรองชุดใหม่</h3>
        <p>{note || "รหัสเหล่านี้จะแสดงเพียงครั้งเดียว กรุณาเก็บไว้ในที่ปลอดภัย"}</p>
      </div>

      <div className={styles.codesGrid}>
        {codes.map((c, i) => (
          <code key={i}>{c}</code>
        ))}
      </div>

      <div className={styles.codesActions}>
        <button
          type="button"
          onClick={copy}
          className={copied ? styles.actionDone : ""}
        >
          {copied ? "คัดลอกแล้ว" : "คัดลอกทั้งหมด"}
        </button>
        <button
          type="button"
          onClick={download}
          className={downloaded ? styles.actionDone : ""}
        >
          {downloaded ? "ดาวน์โหลดแล้ว" : "ดาวน์โหลด .txt"}
        </button>
      </div>

      <label
        className={`${styles.codesConfirm} ${copied || downloaded ? "" : styles.codesConfirmDisabled}`}
      >
        <input
          type="checkbox"
          checked={confirmed}
          disabled={!(copied || downloaded)}
          onChange={(e) => setConfirmed(e.target.checked)}
        />
        <span>ฉันบันทึก Backup codes ไว้ในที่ปลอดภัยแล้ว</span>
      </label>

      <button
        type="button"
        onClick={onConfirm}
        disabled={!canConfirm}
        className={styles.codesSubmit}
      >
        <span>ยืนยันและไปหน้า Login</span><span>→</span>
      </button>
      {!copied && !downloaded && (
        <p className={styles.codesHint}>กรุณาคัดลอกหรือดาวน์โหลดก่อนดำเนินการต่อ</p>
      )}
    </div>
  );
}
