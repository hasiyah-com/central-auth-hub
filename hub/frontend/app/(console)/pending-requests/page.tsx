"use client";

import { useCallback, useEffect, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";
// design system เดียวกับหน้าคอนโซล — .sc = ชุด cx-*
import "../../signal-room.css";
import "../../signal-console.css";

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

const TYPE_LABELS: Record<string, string> = {
  rotate_secret: "Rotate Client Secret", // pragma: allowlist secret
  edit_scope: "แก้ไข Scope",
  edit_allowed_roles: "แก้ไข Allowed Roles",
  edit_redirect_uris: "แก้ไข Redirect URIs",
  change_whitelist_role: "เปลี่ยน Role (1 คน)",
  bulk_change_whitelist_roles: "เปลี่ยน Role (batch)",
};

const STATUS_TONE: Record<string, string> = {
  pending: "warn",
  approved: "signal",
  rejected: "danger",
  cancelled: "",
};

const TABS = [
  { v: "pending", label: "รอตรวจสอบ" },
  { v: "approved", label: "อนุมัติแล้ว" },
  { v: "rejected", label: "ปฏิเสธ" },
] as const;

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
        `Approve request ${(TYPE_LABELS[req.request_type] || req.request_type)}\n` +
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
        `Type: ${TYPE_LABELS[req.request_type] || req.request_type}`
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

  return (
    <div className="sc">
      <Topbar title="Approvals" />

      <section className="cx-command">
        <div>
          <span>
            <span className="cx-dot">
              <i />
            </span>
            change request workflow
          </span>
          <h1>Approvals</h1>
        </div>
        <div className="cx-seg">
          {TABS.map((tab) => (
            <button
              key={tab.v}
              onClick={() => setStatus(tab.v)}
              className={status === tab.v ? "on" : undefined}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </section>

      <main className="cx-document">
        {msg && <div className={`cx-msg ${msg.kind}`}>{msg.text}</div>}

        <section className="cx-panel">
          <header>
            <div>
              <span>developer change requests</span>
              <h2>รายการคำขอ</h2>
            </div>
            <span className="cx-chip mono">
              {loading ? "กำลังโหลด…" : `${items.length} รายการ`}
            </span>
          </header>

          {loading ? (
            <div className="cx-empty">
              <strong>กำลังโหลด…</strong>
            </div>
          ) : items.length === 0 ? (
            <div className="cx-empty">
              <strong>
                ไม่มีคำขอ
                {status === "pending"
                  ? "ที่รอตรวจสอบ"
                  : status === "approved"
                    ? "ที่อนุมัติแล้ว"
                    : "ที่ถูกปฏิเสธ"}
              </strong>
              <span>
                คำขอที่ต้องให้ admin อนุมัติ: rotate secret · edit scope · roles ·
                redirect URIs
              </span>
            </div>
          ) : (
            <div className="cx-req-list">
              {items.map((req) => (
                <article key={req.id} className="cx-req">
                  <div className="cx-req-head">
                    <div>
                      <b>{TYPE_LABELS[req.request_type] || req.request_type}</b>
                      <span className={`cx-chip ${STATUS_TONE[req.status] || ""}`}>
                        {req.status}
                      </span>
                    </div>
                    {req.status === "pending" && (
                      <div className="cx-req-actions">
                        <button
                          onClick={() => approve(req)}
                          disabled={reviewing === req.id}
                          className="cx-act ok"
                        >
                          {reviewing === req.id ? "…" : "อนุมัติ"}
                        </button>
                        <button
                          onClick={() => reject(req)}
                          disabled={reviewing === req.id}
                          className="cx-act no"
                        >
                          ปฏิเสธ
                        </button>
                      </div>
                    )}
                  </div>

                  <dl className="cx-req-meta">
                    <div>
                      <dt>ระบบย่อย</dt>
                      <dd>{req.subsystem_name}</dd>
                    </div>
                    <div>
                      <dt>ผู้ขอ</dt>
                      <dd className="mono">{req.requested_by_email}</dd>
                    </div>
                    <div>
                      <dt>ขอเมื่อ</dt>
                      <dd className="mono">{fmtTime(req.created_at)}</dd>
                    </div>
                    {req.reviewed_at && (
                      <div>
                        <dt>ตรวจเมื่อ</dt>
                        <dd className="mono">{fmtTime(req.reviewed_at)}</dd>
                      </div>
                    )}
                  </dl>

                  {req.request_type !== "rotate_secret" && (
                    <div className="cx-req-payload">
                      <span className="mono">payload ที่ขอเปลี่ยน</span>
                      <code>{JSON.stringify(req.payload, null, 2)}</code>
                    </div>
                  )}

                  {req.reviewer_note && (
                    <div className="cx-req-note">
                      <span className="mono">หมายเหตุจาก admin</span>
                      {req.reviewer_note}
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
