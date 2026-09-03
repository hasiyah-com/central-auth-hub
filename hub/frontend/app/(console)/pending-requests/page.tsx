"use client";

import { useCallback, useEffect, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";

type ChangeRequest = {
  id: string;
  subsystem_id: string;
  subsystem_name: string;
  requested_by: string;
  requested_by_email: string;
  request_type: string;
  payload: Record<string, unknown>;
  status: string;
  reviewer_id: string | null;
  reviewer_note: string | null;
  created_at: string | null;
  reviewed_at: string | null;
};

const TYPE_LABELS: Record<string, { label: string; icon: string }> = {
  rotate_secret: { label: "Rotate Client Secret", icon: "🔑" },
  edit_scope: { label: "แก้ไข Scope", icon: "🎯" },
  edit_allowed_roles: { label: "แก้ไข Allowed Roles", icon: "🧰" },
  edit_redirect_uris: { label: "แก้ไข Redirect URIs", icon: "↩️" },
  change_whitelist_role: { label: "เปลี่ยน Role (1 คน)", icon: "👤" },
  bulk_change_whitelist_roles: { label: "เปลี่ยน Role (batch)", icon: "👥" },
};

const STATUS_TONE: Record<string, "default" | "good" | "warn" | "danger"> = {
  pending: "warn",
  approved: "good",
  rejected: "danger",
  cancelled: "default",
};

function parseUTC(iso: string): Date {
  const hasTz = /[+-]\d{2}:?\d{2}$|Z$/i.test(iso);
  return new Date(hasTz ? iso : iso + "Z");
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  return parseUTC(iso).toLocaleString("th-TH", {
    timeZone: "Asia/Bangkok",
    dateStyle: "short",
    timeStyle: "short",
  });
}

export default function PendingRequestsPage() {
  const [items, setItems] = useState<ChangeRequest[]>([]);
  const [status, setStatus] = useState<string>("pending");
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(
    null
  );
  const [reviewing, setReviewing] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    clientFetch<{ items: ChangeRequest[]; total: number }>(
      `/admin/change-requests?status=${status}&limit=100`
    )
      .then((d) => setItems(d.items || []))
      .catch((e) => setMsg({ kind: "err", text: e.detail || "โหลดไม่สำเร็จ" }))
      .finally(() => setLoading(false));
  }, [status]);

  useEffect(load, [load]);

  async function approve(req: ChangeRequest) {
    if (
      !confirm(
        `Approve request ${TYPE_LABELS[req.request_type]?.label}\n` +
          `Subsystem: ${req.subsystem_name}\n` +
          `Requester: ${req.requested_by_email}\n\nยืนยัน?`
      )
    )
      return;
    setReviewing(req.id);
    setMsg(null);
    try {
      const r = await clientFetch<{ message: string }>(
        `/admin/change-requests/${req.id}/approve`,
        { method: "POST", body: JSON.stringify({}) }
      );
      setMsg({ kind: "ok", text: r.message });
      load();
    } catch (e) {
      const err = e as { detail?: string };
      setMsg({ kind: "err", text: err.detail || "approve ไม่สำเร็จ" });
    } finally {
      setReviewing(null);
    }
  }

  async function reject(req: ChangeRequest) {
    const note = prompt(
      `Reject request — กรุณาใส่เหตุผล (จะถูกส่ง email ให้ requester):\n\n` +
        `Subsystem: ${req.subsystem_name}\n` +
        `Type: ${TYPE_LABELS[req.request_type]?.label}`
    );
    if (!note || !note.trim()) return;
    setReviewing(req.id);
    setMsg(null);
    try {
      const r = await clientFetch<{ message: string }>(
        `/admin/change-requests/${req.id}/reject`,
        { method: "POST", body: JSON.stringify({ note: note.trim() }) }
      );
      setMsg({ kind: "ok", text: r.message });
      load();
    } catch (e) {
      const err = e as { detail?: string };
      setMsg({ kind: "err", text: err.detail || "reject ไม่สำเร็จ" });
    } finally {
      setReviewing(null);
    }
  }

  const actions = <div className="cx-live-actions">{(["pending", "approved", "rejected"] as const).map((item) => <button key={item} type="button" className={status === item ? "active" : ""} onClick={() => setStatus(item)}>{item}</button>)}</div>;

  return (
    <>
      <Topbar title="คำขอ Approve" actions={actions} />
      <main className="cx-document">
        {msg && <div className={`cx-alert ${msg.kind === "err" ? "danger" : ""}`}>{msg.text}</div>}
        <section className="cx-panel">
          <header><div><span className="mono">DEVELOPER CHANGE REQUESTS</span><h2>รายการคำขอ</h2></div><span className="cx-data">{loading ? "LOADING" : `${items.length} REQUESTS`}</span></header>
          {items.length === 0 && !loading ? <div className="cx-diff-empty"><strong>ไม่มีคำขอ {status === "pending" ? "ที่รอตัดสินใจ" : status}</strong><span className="mono">OLD → NEW DIFF WILL APPEAR HERE</span></div> : <div className="cx-request-list">
            {items.map((request) => {
              const typeInfo=TYPE_LABELS[request.request_type] || {label:request.request_type,icon:"•"};
              return <article key={request.id}>
                <header><span className="cx-request-icon">{typeInfo.icon}</span><div><b>{typeInfo.label}</b><small>{request.subsystem_name} · {request.requested_by_email}</small></div><span className={`cx-chip ${request.status === "approved" ? "signal" : request.status === "rejected" ? "danger" : "warn"}`}>{request.status.toUpperCase()}</span></header>
                <div className="cx-request-meta"><span>REQUESTED <b className="mono">{fmtTime(request.created_at)}</b></span><span>REQUEST ID <b className="mono">{request.id.slice(0,12)}</b></span></div>
                {request.request_type !== "rotate_secret" && <pre className="cx-request-payload">{JSON.stringify(request.payload,null,2)}</pre>}
                {request.reviewer_note && <div className="cx-policy-note"><span><b>หมายเหตุจาก Admin:</b> {request.reviewer_note}</span></div>}
                {request.status === "pending" && <footer><button type="button" disabled={reviewing === request.id} onClick={() => approve(request)}>อนุมัติ</button><button type="button" disabled={reviewing === request.id} onClick={() => reject(request)}>ปฏิเสธ</button></footer>}
              </article>;
            })}
          </div>}
        </section>
      </main>
    </>
  );
}
