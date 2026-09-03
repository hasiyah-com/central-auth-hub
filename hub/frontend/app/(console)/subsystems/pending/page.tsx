"use client";

/**
 * Dedicated triage view for pending subsystem registrations.
 *
 * Why a separate page from /subsystems:
 * - /subsystems is a flat table — fine for browsing all subsystems
 * - /subsystems/pending shows ONE card per request with redirect_uris,
 *   scope, and a confirm step before approve/reject — appropriate for
 *   an admin action that creates a long-lived OAuth client.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";
import { mutateWithStepup } from "@/lib/passkey";

type PendingSubsystem = {
  id: string;
  name: string;
  description?: string;
  client_id: string;
  scope?: string;
  whitelist_count: number;
  owner_email?: string;
  created_at?: string;
  redirect_uris?: string | string[];
  [k: string]: unknown;
};

function formatTime(iso?: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("th-TH", {
      timeZone: "Asia/Bangkok",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

/**
 * Backend คืน redirect_uris เป็น **array** (`list(s.redirect_uris or [])`) แต่ข้อมูล
 * เก่าบาง path เคยเก็บเป็น string คั่นด้วย newline/comma — รองรับทั้งสองแบบ.
 * (เดิมรับ string อย่างเดียว → `raw.split is not a function` ตอน render หน้า pending)
 */
function splitUris(raw?: string | string[]): string[] {
  if (!raw) return [];
  const parts = Array.isArray(raw) ? raw : raw.split(/[\n,]+/);
  return parts.map((s) => String(s).trim()).filter(Boolean);
}

export default function PendingSubsystemsPage() {
  const [subs, setSubs] = useState<PendingSubsystem[]>([]);
  const [loading, setLoading] = useState(true);
  const [confirming, setConfirming] = useState<
    { id: string; action: "approve" | "reject" } | null
  >(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(
    null
  );

  function load() {
    setLoading(true);
    // Use the richer /admin/subsystems?status=pending endpoint so we get
    // whitelist_count + owner_email + client_id (which /pending omits).
    clientFetch<PendingSubsystem[]>("/admin/subsystems?status=pending")
      .then((data) => {
        setSubs(data);
        setLoading(false);
      })
      .catch((e) => {
        setMsg({ kind: "err", text: e.detail || "โหลดไม่สำเร็จ" });
        setLoading(false);
      });
  }

  useEffect(load, []);

  async function act(id: string, action: "approve" | "reject") {
    setBusy(id + action);
    setMsg(null);
    setConfirming(null);
    try {
      const r = await mutateWithStepup<{ message: string }>(
        `/admin/subsystems/${id}/${action}`,
        { method: "POST" },
        setVerifying
      );
      setMsg({ kind: "ok", text: r.message });
      load();
    } catch (e) {
      if (e instanceof DOMException && e.name === "NotAllowedError") {
        setMsg({ kind: "err", text: "ยกเลิกการยืนยัน Passkey" });
      } else {
        const d = (e as { detail?: unknown })?.detail;
        const code = typeof d === "object" && d ? (d as { code?: string }).code : undefined;
        setMsg({
          kind: "err",
          text:
            code === "no_passkey"
              ? "ต้องมี Passkey เพื่อยืนยัน — ตั้งค่าที่หน้าความปลอดภัย"
              : typeof d === "string"
                ? d
                : "ทำรายการไม่สำเร็จ",
        });
      }
    } finally {
      setBusy(null);
      setVerifying(false);
    }
  }

  return (
    <>
      {verifying && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-2xl px-6 py-5 shadow-xl flex items-center gap-3 text-sm text-ink-700">
            <span className="animate-pulse text-lg">🔐</span>
            กำลังยืนยันด้วย Passkey… ทำตามที่อุปกรณ์แจ้ง
          </div>
        </div>
      )}
      <Topbar title="คำขอรออนุมัติ" actions={<div className="cx-command-actions"><Link className="cx-button" href="/subsystems">← ระบบย่อยทั้งหมด</Link><span className="cx-chip warn">{loading ? "LOADING" : `${subs.length} PENDING`}</span></div>} />
      <main className="cx-document signal-page signal-page-compact">
        <section className="cx-review-head"><span className="mono">REVIEW QUEUE</span><b>ตรวจ OAuth client, Redirect URI และ Scope ก่อนตัดสินใจ</b></section>

        {msg && (
          <div className={`cx-alert ${msg.kind === "err" ? "danger" : ""}`}>
            {msg.text}
          </div>
        )}

        {!loading && subs.length === 0 && (
          <div className="cx-empty">
            <div>◇</div><div>
            <b>
              ไม่มีคำขอรออนุมัติ
            </b>
            <small>
              ระบบย่อยใหม่จะปรากฏที่นี่เมื่อมีการลงทะเบียน
            </small></div>
          </div>
        )}

        <section className="cx-panel"><header><div><span className="mono">PENDING REGISTRATIONS</span><h2>คำขอระบบย่อย</h2></div></header><div className="cx-request-list">
          {subs.map((s) => {
            const uris = splitUris(s.redirect_uris);
            const isConfirmingThis = confirming?.id === s.id;
            return (
              <article key={s.id}>
                <div className="flex items-start gap-4 mb-4">
                  <div className="flex-1">
                    <div className="text-lg font-bold text-ink-900">
                      {s.name}
                    </div>
                    {s.description && (
                      <div className="text-sm text-ink-600 mt-1">
                        {s.description}
                      </div>
                    )}
                    <div className="text-xs text-ink-500 font-mono mt-2">
                      {s.client_id}
                    </div>
                  </div>
                  <div className="text-right text-xs text-ink-500">
                    <div>ลงทะเบียนเมื่อ</div>
                    <div className="font-mono mt-0.5">
                      {formatTime(s.created_at)}
                    </div>
                  </div>
                </div>

                <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm mb-5">
                  <div>
                    <dt className="text-xs text-ink-500 uppercase tracking-wide font-semibold">
                      เจ้าของ
                    </dt>
                    <dd className="mt-1 text-ink-800">
                      {s.owner_email || "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-500 uppercase tracking-wide font-semibold">
                      Whitelist
                    </dt>
                    <dd className="mt-1 font-mono text-ink-800">
                      {s.whitelist_count} คน
                    </dd>
                  </div>
                  <div className="col-span-2">
                    <dt className="text-xs text-ink-500 uppercase tracking-wide font-semibold">
                      Scope
                    </dt>
                    <dd className="mt-1 font-mono text-xs text-ink-700">
                      {s.scope || "—"}
                    </dd>
                  </div>
                  <div className="col-span-2">
                    <dt className="text-xs text-ink-500 uppercase tracking-wide font-semibold">
                      Redirect URIs
                    </dt>
                    <dd className="mt-1">
                      {uris.length === 0 ? (
                        <span className="text-ink-400 text-xs">—</span>
                      ) : (
                        <ul className="space-y-1">
                          {uris.map((u) => (
                            <li
                              key={u}
                              className="font-mono text-xs text-ink-700 break-all"
                            >
                              {u}
                            </li>
                          ))}
                        </ul>
                      )}
                    </dd>
                  </div>
                </dl>

                {isConfirmingThis ? (
                  <div className="flex items-center gap-3 pt-4 border-t border-ink-100">
                    <div className="text-sm text-ink-700 font-medium">
                      {confirming.action === "approve"
                        ? "ยืนยันอนุมัติ?"
                        : "ยืนยันปฏิเสธ?"}
                    </div>
                    <button
                      onClick={() => act(s.id, confirming.action)}
                      disabled={busy === s.id + confirming.action}
                      className={
                        "ml-auto px-4 py-2 rounded-md text-white text-xs font-semibold disabled:opacity-50 " +
                        (confirming.action === "approve"
                          ? "bg-emerald-600 hover:bg-emerald-700"
                          : "bg-rose-600 hover:bg-rose-700")
                      }
                    >
                      {busy === s.id + confirming.action ? "..." : "ยืนยัน"}
                    </button>
                    <button
                      onClick={() => setConfirming(null)}
                      className="px-4 py-2 rounded-md border border-ink-200 text-ink-600 text-xs font-semibold hover:bg-ink-50"
                    >
                      ยกเลิก
                    </button>
                  </div>
                ) : (
                  <div className="flex gap-2 pt-4 border-t border-ink-100">
                    <button
                      onClick={() => setConfirming({ id: s.id, action: "approve" })}
                      className="px-4 py-2 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold"
                    >
                      อนุมัติ
                    </button>
                    <button
                      onClick={() => setConfirming({ id: s.id, action: "reject" })}
                      className="px-4 py-2 rounded-md bg-rose-600 hover:bg-rose-700 text-white text-sm font-semibold"
                    >
                      ปฏิเสธ
                    </button>
                  </div>
                )}
              </article>
            );
          })}
        </div></section>
      </main>
    </>
  );
}
