"use client";

/**
 * Recovery Tickets — admin triage คำขอกู้บัญชี (ทางสุดท้าย).
 * admin ยืนยันตัวตนนอกระบบ (บัตร นศ./ปชช.) → บันทึก evidence → approve.
 * NORMAL = 1 admin · HIGH = 2 admin ต่างคน (four-eyes). approve ครบ → one-time link ให้ user.
 */

import { useCallback, useEffect, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { Badge } from "@/components/Badge";
import {
  adminListRecoveryTickets,
  adminApproveTicket,
  adminRejectTicket,
  type RecoveryTicket,
} from "@/lib/passkey";

const EVIDENCE = [
  { v: "student_card", label: "บัตรนักศึกษา" },
  { v: "citizen_id", label: "บัตรประชาชน" },
  { v: "other", label: "อื่นๆ" },
];

export default function RecoveryTicketsPage() {
  const [items, setItems] = useState<RecoveryTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [verifying, setVerifying] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [link, setLink] = useState<{ id: string; url: string } | null>(null);
  // per-ticket evidence form
  const [form, setForm] = useState<Record<string, { evidence_type: string; remark: string }>>({});

  const load = useCallback(() => {
    setLoading(true);
    adminListRecoveryTickets("pending")
      .then((d) => setItems(d.items))
      .catch((e) => setMsg({ kind: "err", text: e?.detail || "โหลดไม่สำเร็จ" }))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const f = (id: string) => form[id] || { evidence_type: "student_card", remark: "" };

  async function approve(t: RecoveryTicket) {
    setBusy(t.id + "a");
    setMsg(null);
    try {
      const r = await adminApproveTicket(
        t.id,
        { evidence_type: f(t.id).evidence_type, remark: f(t.id).remark },
        setVerifying
      );
      if (r.relink_url) {
        setLink({ id: t.id, url: r.relink_url });
        setMsg({ kind: "ok", text: "อนุมัติครบ — คัดลอกลิงก์ให้ผู้ใช้" });
      } else {
        setMsg({
          kind: "ok",
          text: `บันทึกการอนุมัติแล้ว (${r.approvals}/${r.required}) — รอ admin อีกคน (four-eyes)`,
        });
      }
      load();
    } catch (e) {
      const d = (e as { detail?: unknown })?.detail;
      setMsg({
        kind: "err",
        text: typeof d === "string" ? d : "อนุมัติไม่สำเร็จ",
      });
    } finally {
      setBusy(null);
    }
  }

  async function reject(t: RecoveryTicket) {
    if (!confirm(`ปฏิเสธคำขอของ ${t.email}?`)) return;
    setBusy(t.id + "r");
    try {
      await adminRejectTicket(t.id, setVerifying);
      setMsg({ kind: "ok", text: "ปฏิเสธแล้ว" });
      load();
    } catch (e) {
      setMsg({ kind: "err", text: (e as { detail?: string })?.detail || "ไม่สำเร็จ" });
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      {verifying && (
        <div className="fixed inset-0 z-[60] grid place-items-center bg-black/40">
          <div className="bg-white rounded-2xl px-6 py-5 shadow-xl text-sm text-ink-700">
            🔐 กำลังยืนยันด้วย Passkey…
          </div>
        </div>
      )}
      <Topbar title="คำขอกู้บัญชี (Recovery Tickets)" />
      <main className="p-8 max-w-4xl mx-auto w-full">
        <p className="text-xs text-ink-500 mb-4">
          ⚠️ ยืนยันตัวตนผู้ขอ<strong>ต่อหน้า</strong> (บัตร นศ./ปชช.) ก่อนอนุมัติเสมอ —
          HIGH ต้อง admin 2 คน (four-eyes)
        </p>

        {msg && (
          <div
            className={
              "mb-4 p-3 rounded-lg text-sm " +
              (msg.kind === "ok"
                ? "bg-emerald-50 border border-emerald-200 text-emerald-700"
                : "bg-rose-50 border border-rose-200 text-rose-700")
            }
          >
            {msg.text}
          </div>
        )}

        {link && (
          <div className="mb-4 p-4 rounded-lg bg-brand-50 border border-brand-200">
            <div className="text-xs font-bold text-brand-900 mb-1">
              🔗 ลิงก์กู้บัญชี (ใช้ครั้งเดียว · 30 นาที) — ส่งให้ผู้ใช้เปิดเอง
            </div>
            <div className="bg-white border border-brand-200 rounded p-2 font-mono text-[11px] break-all">
              {link.url}
            </div>
            <button
              onClick={() => navigator.clipboard?.writeText(link.url)}
              className="mt-2 text-xs px-3 py-1 rounded bg-brand-600 text-white font-semibold"
            >
              คัดลอกลิงก์
            </button>
          </div>
        )}

        {loading ? (
          <div className="text-ink-400 text-sm">กำลังโหลด…</div>
        ) : items.length === 0 ? (
          <div className="bg-white rounded-xl border border-ink-200 p-12 text-center">
            <div className="text-5xl mb-3">✨</div>
            <div className="font-semibold text-ink-700">ไม่มีคำขอรออนุมัติ</div>
          </div>
        ) : (
          <div className="space-y-4">
            {items.map((t) => (
              <div
                key={t.id}
                className="bg-white rounded-xl border border-ink-200 p-5 shadow-sm"
              >
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div>
                    <div className="font-bold text-ink-900">{t.email}</div>
                    <div className="text-xs text-ink-500 mt-0.5">
                      แจ้งหาย: {t.credential_type || "—"} · {t.reason || "ไม่ระบุเหตุผล"}
                    </div>
                    <div className="text-[11px] text-ink-400 font-mono mt-1">
                      Ticket {t.id.slice(0, 8)} ·{" "}
                      {t.created_at
                        ? new Date(t.created_at).toISOString().slice(0, 16).replace("T", " ")
                        : ""}
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <Badge tone={t.recovery_level === "HIGH" ? "danger" : "warn"}>
                      {t.recovery_level}
                    </Badge>
                    <span className="text-[11px] text-ink-500 font-mono">
                      อนุมัติ {t.approvals}/{t.required}
                    </span>
                  </div>
                </div>

                {/* Evidence form */}
                <div className="mt-4 flex flex-wrap items-end gap-2 border-t border-ink-100 pt-3">
                  <div>
                    <label className="block text-[10px] font-bold text-ink-500 uppercase mb-1">
                      หลักฐานที่ตรวจ
                    </label>
                    <select
                      value={f(t.id).evidence_type}
                      onChange={(e) =>
                        setForm((s) => ({
                          ...s,
                          [t.id]: { ...f(t.id), evidence_type: e.target.value },
                        }))
                      }
                      className="px-2 py-1.5 rounded border border-ink-200 text-sm"
                    >
                      {EVIDENCE.map((ev) => (
                        <option key={ev.v} value={ev.v}>
                          {ev.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <input
                    value={f(t.id).remark}
                    onChange={(e) =>
                      setForm((s) => ({
                        ...s,
                        [t.id]: { ...f(t.id), remark: e.target.value },
                      }))
                    }
                    placeholder="หมายเหตุ (เช่น เลขบัตร, ผู้ตรวจ)"
                    className="flex-1 min-w-[180px] px-3 py-1.5 rounded border border-ink-200 text-sm"
                  />
                  <button
                    onClick={() => approve(t)}
                    disabled={busy === t.id + "a"}
                    className="px-4 py-1.5 rounded-lg bg-emerald-600 text-white text-sm font-semibold hover:bg-emerald-700 disabled:opacity-50"
                  >
                    {busy === t.id + "a"
                      ? "…"
                      : t.required > t.approvals + 1
                        ? "อนุมัติ (1/2)"
                        : "อนุมัติ → ออกลิงก์"}
                  </button>
                  <button
                    onClick={() => reject(t)}
                    disabled={busy === t.id + "r"}
                    className="px-3 py-1.5 rounded-lg border border-rose-200 text-rose-700 text-sm font-semibold hover:bg-rose-50 disabled:opacity-50"
                  >
                    ปฏิเสธ
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </>
  );
}
