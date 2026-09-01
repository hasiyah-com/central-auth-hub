"use client";

import { useCallback, useEffect, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { Badge } from "@/components/Badge";
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

  return (
    <>
      <Topbar title="คำขอ Approve · Developer Change Requests" />
      <main className="signal-page signal-page-compact space-y-6">
        <div className="flex items-end justify-between gap-3 flex-wrap">
          <div>
            <h2 className="text-sm font-bold text-ink-500 uppercase tracking-wider">
              Change Request Workflow
            </h2>
            <p className="text-xs text-ink-400 mt-1">
              Sensitive operations (rotate secret · edit scope · roles · redirect URIs) ต้อง admin approve
            </p>
          </div>
          <div className="inline-flex rounded-lg border border-ink-200 bg-white overflow-hidden text-xs font-semibold">
            {(["pending", "approved", "rejected"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setStatus(s)}
                className={
                  "px-3 py-2 transition border-r last:border-r-0 border-ink-200 " +
                  (status === s
                    ? "bg-brand-600 text-white"
                    : "text-ink-600 hover:bg-ink-50")
                }
              >
                {s === "pending"
                  ? "⏳ Pending"
                  : s === "approved"
                  ? "✅ Approved"
                  : "🛑 Rejected"}
              </button>
            ))}
          </div>
        </div>

        {msg && (
          <div
            className={
              "p-3 rounded-lg text-sm " +
              (msg.kind === "ok"
                ? "bg-emerald-50 border border-emerald-200 text-emerald-700"
                : "bg-rose-50 border border-rose-200 text-rose-700")
            }
          >
            {msg.text}
          </div>
        )}

        {loading ? (
          <div className="text-ink-400 text-sm">กำลังโหลด…</div>
        ) : items.length === 0 ? (
          <div className="bg-white border border-ink-200 rounded-xl p-12 text-center text-ink-400">
            ไม่มี request {status === "pending" ? "ที่รอ review" : status}
          </div>
        ) : (
          <div className="space-y-3">
            {items.map((req) => {
              const typeInfo = TYPE_LABELS[req.request_type] || {
                label: req.request_type,
                icon: "📝",
              };
              return (
                <div
                  key={req.id}
                  className="bg-white border border-ink-200 rounded-xl p-5 shadow-sm"
                >
                  <div className="flex items-start justify-between gap-4 flex-wrap">
                    <div className="flex-1 min-w-[260px]">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-xl">{typeInfo.icon}</span>
                        <span className="font-extrabold text-ink-900">
                          {typeInfo.label}
                        </span>
                        <Badge tone={STATUS_TONE[req.status] || "default"}>
                          {req.status.toUpperCase()}
                        </Badge>
                      </div>
                      <div className="text-sm text-ink-700">
                        <strong>{req.subsystem_name}</strong>{" "}
                        <span className="text-ink-400">โดย</span>{" "}
                        <span className="font-mono">{req.requested_by_email}</span>
                      </div>
                      <div className="text-[11px] text-ink-400 font-mono mt-1">
                        ขอเมื่อ {fmtTime(req.created_at)}
                        {req.reviewed_at && (
                          <>
                            {" · "}review {fmtTime(req.reviewed_at)}
                          </>
                        )}
                      </div>
                    </div>
                    {req.status === "pending" && (
                      <div className="flex gap-2">
                        <button
                          onClick={() => approve(req)}
                          disabled={reviewing === req.id}
                          className="px-3 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold disabled:opacity-50"
                        >
                          {reviewing === req.id ? "…" : "✅ Approve"}
                        </button>
                        <button
                          onClick={() => reject(req)}
                          disabled={reviewing === req.id}
                          className="px-3 py-2 rounded-lg bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold disabled:opacity-50"
                        >
                          🛑 Reject
                        </button>
                      </div>
                    )}
                  </div>

                  {/* Payload diff */}
                  {req.request_type !== "rotate_secret" && (
                    <div className="mt-3 bg-ink-50 rounded-lg p-3 text-[12px] font-mono break-all">
                      <div className="text-[10px] font-bold uppercase tracking-wider text-ink-500 mb-1">
                        Payload ที่ขอเปลี่ยน
                      </div>
                      <pre className="text-ink-900 whitespace-pre-wrap">
                        {JSON.stringify(req.payload, null, 2)}
                      </pre>
                    </div>
                  )}

                  {req.reviewer_note && (
                    <div className="mt-3 bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs">
                      <strong>หมายเหตุจาก admin:</strong> {req.reviewer_note}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </main>
    </>
  );
}
