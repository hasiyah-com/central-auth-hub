"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";
import { parseUserAgent } from "@/lib/ua";

type AuditLog = {
  id: string; actor_id: string | null; actor_email: string | null; action: string;
  target_type: string | null; target_id: string | null; ip: string | null;
  metadata: Record<string, unknown> | null; created_at: string | null;
};
type AuditResponse = { items: AuditLog[]; total: number; skip: number; limit: number };
const PAGE_SIZE = 50;

function formatTime(value: string | null) {
  if (!value) return "—";
  const zoned = /[+-]\d{2}:?\d{2}$|Z$/i.test(value) ? value : value + "Z";
  return new Date(zoned).toLocaleString("th-TH", { timeZone: "Asia/Bangkok", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

function tone(action: string) {
  if (/rejected|failed|blocked/i.test(action)) return "danger";
  if (/revoked|suspended/i.test(action)) return "warn";
  if (/approved|success|login/i.test(action)) return "signal";
  return "outline";
}

function AuditPageInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const targetId = searchParams.get("target_id");
  const targetEmail = searchParams.get("target_email");
  const actorId = searchParams.get("actor_id");
  const actorEmail = searchParams.get("actor_email");
  const scopeId = targetId || actorId;
  const scopeEmail = targetEmail || actorEmail;
  const [data, setData] = useState<AuditResponse | null>(null);
  const [action, setAction] = useState("");
  const [targetType, setTargetType] = useState(targetId ? "user" : "");
  const [skip, setSkip] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setLoading(true); setError(null);
    const query = new URLSearchParams({ skip: String(skip), limit: String(PAGE_SIZE) });
    if (action) query.set("action", action);
    if (targetType) query.set("target_type", targetType);
    if (targetId) query.set("target_id", targetId);
    if (actorId) query.set("actor_id", actorId);
    clientFetch<AuditResponse>(`/admin/audit?${query.toString()}`).then(setData).catch((cause) => setError(cause.detail || "โหลด Audit Log ไม่สำเร็จ")).finally(() => setLoading(false));
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [action, targetType, targetId, actorId, skip]);
  useEffect(() => setSkip(0), [action, targetType, targetId, actorId]);

  const total = data?.total ?? 0;
  const page = Math.floor(skip / PAGE_SIZE) + 1;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      <Topbar title="Audit Log" />
      <main className="cx-document">
        <section className="cx-chain"><span className="cx-shield-mark">✓</span><div><span className="mono">HASH CHAIN STATUS</span><b>Append-only audit trail</b></div><span className="cx-chip signal"><i className="cx-dot"><i /></i>VERIFIED</span></section>
        {scopeId && <div className="cx-policy-note"><span>กำลังดู Log ของ <b>{scopeEmail || scopeId}</b> เท่านั้น</span><button type="button" onClick={() => router.push("/audit")}>ดูทั้งหมด</button></div>}
        {error && <div className="cx-alert danger">{error}</div>}
        <section className="cx-panel">
          <header><div><span className="mono">IMMUTABLE AUDIT TRAIL</span><h2>เหตุการณ์ทั้งหมด</h2></div><span className="cx-data">{loading ? "LOADING" : `${data?.items.length ?? 0} / ${total} RECORDS`}</span></header>
          <div className="cx-toolbar">
            <label><SearchIcon /><input value={action} onChange={(event) => setAction(event.target.value)} placeholder="Actor, action, target หรือ IP" /></label>
            <select value={targetType} onChange={(event) => setTargetType(event.target.value)}>
              <option value="">ทุก target</option><option value="user">user</option><option value="subsystem">subsystem</option><option value="access_list">access_list</option><option value="login_session">login_session</option>
            </select>
          </div>
          <div className="cx-table-wrap"><table>
            <thead><tr><th>TIME · ASIA/BANGKOK</th><th>ACTOR</th><th>ACTION</th><th>TARGET</th><th>SOURCE IP / DEVICE</th><th>DETAIL</th></tr></thead>
            <tbody>
              {!loading && (data?.items.length ?? 0) === 0 && <tr><td colSpan={6}><div className="cx-empty"><strong>ไม่พบ Audit Log</strong><span className="mono">NO MATCHING EVENTS</span></div></td></tr>}
              {data?.items.map((row) => {
                const ua = parseUserAgent((row.metadata as { user_agent?: string } | null)?.user_agent);
                return <tr key={row.id}>
                  <td><code>{formatTime(row.created_at)}</code></td>
                  <td><span>{row.actor_email || "system"}</span><small className="cx-data">{row.actor_id || "SYSTEM ACTOR"}</small></td>
                  <td><span className={`cx-chip ${tone(row.action)}`}>{row.action}</span></td>
                  <td><span>{row.target_type || "—"}</span><small className="cx-data">{row.target_id || "NO TARGET ID"}</small></td>
                  <td><code>{row.ip || "—"}</code><small className="cx-data">{ua?.label || "ไม่ทราบอุปกรณ์"}</small></td>
                  <td><details className="cx-audit-detail"><summary>ดูรายละเอียด</summary><pre>{JSON.stringify(row.metadata || {}, null, 2)}</pre></details></td>
                </tr>;
              })}
            </tbody>
          </table></div>
          <div className="cx-pagination"><button type="button" disabled={skip === 0 || loading} onClick={() => setSkip(Math.max(0, skip - PAGE_SIZE))}>← ก่อนหน้า</button><span className="mono">PAGE {page} / {pages}</span><button type="button" disabled={skip + PAGE_SIZE >= total || loading} onClick={() => setSkip(skip + PAGE_SIZE)}>ถัดไป →</button></div>
        </section>
      </main>
    </>
  );
}

function SearchIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg> }

export default function AuditPage() { return <Suspense fallback={null}><AuditPageInner /></Suspense> }
