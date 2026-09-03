"use client";

/**
 * Recovery Tickets — admin triage คำขอกู้บัญชี (ทางสุดท้าย).
 * admin ยืนยันตัวตนนอกระบบ (บัตร นศ./ปชช.) → บันทึก evidence → approve.
 * NORMAL = 1 admin · HIGH = 2 admin ต่างคน (four-eyes). approve ครบ → one-time link ให้ user.
 */

import { useCallback, useEffect, useState } from "react";
import { Topbar } from "@/components/Topbar";
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

  const high = items.filter((item) => item.recovery_level === "HIGH").length;
  const actions = <button className="cx-primary-action" type="button" onClick={load}>↻ รีเฟรชรายการ</button>;
  return (
    <>
      {verifying && <div className="fixed inset-0 z-[60] grid place-items-center bg-black/40"><div className="cx-loading-card">กำลังยืนยันด้วย Passkey…</div></div>}
      <Topbar title="คำขอกู้บัญชี" actions={actions} />
      <main className="cx-document">
        <section className="cx-kpis four">
          <article className="cx-kpi"><span className="mono">PENDING TICKETS</span><strong>{items.length}</strong><small className="mono">REVIEW QUEUE</small></article>
          <article className="cx-kpi danger"><span className="mono">HIGH RECOVERY RISK</span><strong>{high}</strong><small className="mono">FOUR-EYES REQUIRED</small></article>
          <article className="cx-kpi"><span className="mono">STANDARD REVIEW</span><strong>{items.length-high}</strong><small className="mono">ONE ADMIN</small></article>
          <article className="cx-kpi signal"><span className="mono">ONE-TIME LINK</span><strong>{link ? 1 : 0}</strong><small className="mono">READY TO COPY</small></article>
        </section>
        {msg && <div className={`cx-alert ${msg.kind === "err" ? "danger" : ""}`}>{msg.text}</div>}
        {link && <section className="cx-panel"><header><div><span className="mono">ONE-TIME SECRET · 30 MINUTES</span><h2>ลิงก์กู้บัญชี</h2></div><button type="button" onClick={() => navigator.clipboard?.writeText(link.url)}>คัดลอกลิงก์</button></header><pre className="cx-recovery-link">{link.url}</pre></section>}
        <section className="cx-panel">
          <header><div><span className="mono">ACCOUNT RECOVERY TRIAGE</span><h2>คำขอกู้บัญชีที่รอตรวจสอบ</h2></div><span className="cx-chip warn">STEP-UP REQUIRED</span></header>
          <div className="cx-recovery-list">
            {!loading && items.length === 0 && <div className="cx-empty"><strong>ไม่มีคำขอรออนุมัติ</strong><span className="mono">RECOVERY QUEUE CLEAR</span></div>}
            {items.map((ticket) => <article key={ticket.id}>
              <header><div><b>{ticket.email}</b><small>Ticket {ticket.id.slice(0,8)} · {ticket.credential_type || "ไม่ระบุ Credential"}</small></div><span className={`cx-chip ${ticket.recovery_level === "HIGH" ? "danger" : "warn"}`}>{ticket.recovery_level}</span></header>
              <p>{ticket.reason || "ไม่ระบุเหตุผล"}</p>
              <div className="cx-recovery-evidence">
                <label>หลักฐานที่ตรวจ<select value={f(ticket.id).evidence_type} onChange={(event)=>setForm((state)=>({...state,[ticket.id]:{...f(ticket.id),evidence_type:event.target.value}}))}>{EVIDENCE.map((evidence)=><option key={evidence.v} value={evidence.v}>{evidence.label}</option>)}</select></label>
                <label>หมายเหตุ<input value={f(ticket.id).remark} onChange={(event)=>setForm((state)=>({...state,[ticket.id]:{...f(ticket.id),remark:event.target.value}}))} placeholder="เลขบัตรหรือชื่อผู้ตรวจ" /></label>
                <span className="mono">APPROVAL {ticket.approvals}/{ticket.required}</span>
              </div>
              <footer><button type="button" disabled={busy===ticket.id+"a"} onClick={()=>approve(ticket)}>อนุมัติ{ticket.required>ticket.approvals+1?" (1/2)":" → ออกลิงก์"}</button><button type="button" disabled={busy===ticket.id+"r"} onClick={()=>reject(ticket)}>ปฏิเสธ</button></footer>
            </article>)}
          </div>
        </section>
        <section className="cx-grid two"><article className="cx-panel"><header><div><span className="mono">APPROVAL FLOW</span><h2>ขั้นตอนอนุมัติที่ปลอดภัย</h2></div></header><div className="cx-recovery-flow"><span><b className="mono">01</b><small>ตรวจหลักฐานตัวตน</small></span><span>→</span><span><b className="mono">02</b><small>ยืนยัน Step-up</small></span><span>→</span><span><b className="mono">03</b><small>สร้าง Recovery link</small></span></div></article><article className="cx-panel"><header><div><span className="mono">SECURITY POLICY</span><h2>การอนุมัติแบบ Four-eyes</h2></div></header><div className="cx-empty"><strong>คำขอความเสี่ยงสูงต้อง Admin 2 คน</strong><span className="mono">HIGH RISK RECOVERY CONTROL</span></div></article></section>
      </main>
    </>
  );
}
