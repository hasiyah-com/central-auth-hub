"use client";

import { useState } from "react";
import { clientFetch } from "@/lib/api";
import { runWithStepup } from "@/lib/passkey";

type PreviewRow = {
  row: number;
  email: string;
  name: string;
  current_status: string;
  new_status: string;
  changed: boolean;
};
type Preview = {
  rows: PreviewRow[];
  errors: { row: number; email: string; message: string }[];
  total: number;
  changed: number;
};

function errorText(error: unknown): string {
  if (typeof error === "object" && error && "detail" in error) {
    const detail = (error as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (typeof detail === "object" && detail && "errors" in detail) {
      return "ข้อมูลเปลี่ยนหรือมีแถวที่ไม่ถูกต้อง กรุณาตรวจไฟล์ใหม่";
    }
  }
  return "ดำเนินการไม่สำเร็จ กรุณาลองอีกครั้ง";
}

export function StatusImportModal({ onClose, onSaved }: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [filename, setFilename] = useState("");
  const [encoded, setEncoded] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function downloadTemplate() {
    setError(null);
    try {
      const response = await fetch("/api/proxy/admin/users/status-import/template", {
        credentials: "include",
      });
      if (!response.ok) throw new Error("ดาวน์โหลดแม่แบบไม่สำเร็จ");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "user-status-template.xlsx";
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      setError("ดาวน์โหลดแม่แบบไม่สำเร็จ กรุณาลองอีกครั้ง");
    }
  }

  async function selectFile(file?: File) {
    setPreview(null);
    setEncoded("");
    setError(null);
    setSuccess(null);
    setFilename(file?.name ?? "");
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".xlsx") || file.size > 1_000_000) {
      setError("เลือกไฟล์ .xlsx ขนาดไม่เกิน 1 MB");
      return;
    }
    setBusy(true);
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      for (let i = 0; i < bytes.length; i += 8192) {
        binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
      }
      const file_base64 = btoa(binary);
      const result = await clientFetch<Preview>("/admin/users/status-import/preview", {
        method: "POST",
        body: JSON.stringify({ file_base64 }),
      });
      setEncoded(file_base64);
      setPreview(result);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    if (!preview || preview.errors.length || !encoded || !preview.changed) return;
    setBusy(true);
    setError(null);
    try {
      const expected_statuses = Object.fromEntries(
        preview.rows.map((row) => [row.email, row.current_status])
      );
      const result = await runWithStepup(
        () => clientFetch<{ changed: number; unchanged: number }>(
          "/admin/users/status-import/apply",
          {
            method: "POST",
            body: JSON.stringify({ file_base64: encoded, expected_statuses }),
            stepupMode: "throw",
          }
        ),
        setVerifying
      );
      setSuccess(`เปลี่ยนสถานะสำเร็จ ${result.changed} คน (คงเดิม ${result.unchanged} คน)`);
      setPreview(null);
      setEncoded("");
      onSaved();
    } catch (e) {
      setError(errorText(e));
      // Recheck database state before another attempt, including on a 409 conflict.
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4" role="presentation">
      <section role="dialog" aria-modal="true" aria-labelledby="status-import-title"
        className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <header className="flex items-start justify-between border-b border-slate-200 px-6 py-5">
          <div>
            <h2 id="status-import-title" className="text-xl font-bold text-slate-900">Import / Export สถานะผู้ใช้</h2>
            <p className="mt-1 text-sm text-slate-600">นำเข้าไฟล์ Excel เพื่อเปลี่ยนสถานะผู้ใช้หลายคนพร้อมกัน</p>
          </div>
          <button type="button" onClick={onClose} disabled={busy || verifying}
            aria-label="ปิด" className="rounded-lg px-2 text-xl text-slate-500 hover:bg-slate-100 disabled:opacity-50">×</button>
        </header>
        <div className="space-y-5 overflow-y-auto px-6 py-5">
          <p className="text-sm text-slate-700">
            1. ดาวน์โหลดแม่แบบ 2. กรอก <code>email</code> และ <code>new_status</code> ในชีต <code>status_updates</code>
            3. เลือกไฟล์เพื่อตรวจสอบก่อนยืนยัน (สูงสุด 500 คน)
          </p>
          <button type="button" onClick={() => void downloadTemplate()}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-800 hover:bg-slate-50">
            Export แม่แบบ (.xlsx)
          </button>
          <label className="block text-sm font-semibold text-slate-800">
            เลือกไฟล์ .xlsx
            <input type="file" accept=".xlsx" disabled={busy || verifying}
              onChange={(e) => { void selectFile(e.target.files?.[0]); }}
              className="mt-2 block w-full rounded-lg border border-slate-300 p-2 text-sm" />
          </label>
          {filename && <p className="text-xs text-slate-500">ไฟล์: {filename}</p>}
          {busy && <p role="status" className="text-sm text-slate-600">{verifying ? "กำลังยืนยันตัวตน…" : "กำลังดำเนินการ…"}</p>}
          {error && <p role="alert" className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
          {success && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">{success}</p>}
          {preview && (
            <div className="space-y-3">
              <p className="text-sm font-semibold text-slate-900">
                ตรวจพบ {preview.total} แถว · จะเปลี่ยน {preview.changed} คน · ข้อผิดพลาด {preview.errors.length} แถว
              </p>
              {preview.errors.length > 0 && (
                <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
                  <p className="font-semibold">กรุณาแก้ทุกแถวที่ผิดแล้วนำเข้าใหม่ ระบบยังไม่เปลี่ยนสถานะใคร</p>
                  {preview.errors.map((item) => <p key={item.row}>แถว {item.row}: {item.email || "—"} — {item.message}</p>)}
                </div>
              )}
              {preview.rows.length > 0 && (
                <div className="max-h-72 overflow-auto rounded-lg border border-slate-200">
                  <table className="w-full text-left text-sm">
                    <thead className="sticky top-0 bg-slate-100 text-slate-700">
                      <tr><th className="p-2">แถว</th><th className="p-2">ผู้ใช้</th><th className="p-2">สถานะเดิม</th><th className="p-2">สถานะใหม่</th></tr>
                    </thead>
                    <tbody>{preview.rows.map((item) => (
                      <tr key={item.row} className="border-t border-slate-100">
                        <td className="p-2">{item.row}</td>
                        <td className="p-2"><strong>{item.name}</strong><br /><span className="text-xs text-slate-500">{item.email}</span></td>
                        <td className="p-2">{item.current_status}</td>
                        <td className="p-2">{item.new_status}{!item.changed && " (คงเดิม)"}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
              {preview.rows.some((r) => ["deleted", "graduated", "resigned"].includes(r.new_status) && r.changed) && (
                <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
                  สถานะ deleted, graduated และ resigned จะเพิกถอนสิทธิ์ระบบย่อยตามกติกาปัจจุบัน
                </p>
              )}
            </div>
          )}
        </div>
        <footer className="flex justify-end gap-3 border-t border-slate-200 px-6 py-4">
          <button type="button" onClick={onClose} disabled={busy || verifying}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm disabled:opacity-50">ปิด</button>
          <button type="button" onClick={() => void apply()}
            disabled={busy || verifying || !preview || !!preview.errors.length || !preview.changed}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
            ยืนยันการเปลี่ยนสถานะ
          </button>
        </footer>
      </section>
    </div>
  );
}
