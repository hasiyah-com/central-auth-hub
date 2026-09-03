"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";

type Subsystem = {
  id: string; name: string; description?: string; client_id: string; status: string;
  scope?: string; access_policy?: string; whitelist_count: number;
  health?: { status: "online" | "healthy" | "degraded" | "down" | "unknown"; latency_ms?: number; checked_at?: string; error?: string } | null;
  owner_email?: string; created_at?: string; approved_at?: string;
};

export default function SubsystemsPage() {
  const [subs, setSubs] = useState<Subsystem[]>([]);
  const [filter, setFilter] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"name" | "newest">("name");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  function load() {
    clientFetch<Subsystem[]>("/admin/subsystems").then(setSubs).catch((cause) => setMsg({ kind: "err", text: cause.detail || "โหลดไม่สำเร็จ" }));
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, []);

  async function act(id: string, action: "approve" | "reject") {
    setBusy(id + action); setMsg(null);
    try {
      const response = await clientFetch<{ message: string }>(`/admin/subsystems/${id}/${action}`, { method: "POST" });
      setMsg({ kind: "ok", text: response.message }); load();
    } catch (cause) {
      setMsg({ kind: "err", text: (cause as { detail?: string }).detail || "ทำรายการไม่สำเร็จ" });
    } finally { setBusy(null); }
  }

  const counts = useMemo(() => ({
    total: subs.length,
    active: subs.filter((item) => item.status === "active").length,
    pending: subs.filter((item) => item.status === "pending").length,
    suspended: subs.filter((item) => item.status === "suspended").length,
  }), [subs]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    let rows = subs.filter((item) => !filter || item.status === filter);
    if (needle) rows = rows.filter((item) => [item.name, item.client_id, item.owner_email, item.description].filter(Boolean).some((value) => String(value).toLowerCase().includes(needle)));
    return [...rows].sort((a, b) => sort === "name" ? a.name.localeCompare(b.name, "th") : String(b.created_at || "").localeCompare(String(a.created_at || "")));
  }, [subs, filter, q, sort]);

  const actions = <Link href="/subsystems/pending" className="cx-primary-action">รายการรออนุมัติ · {counts.pending}</Link>;

  return (
    <>
      <Topbar title="ระบบย่อย" actions={actions} />
      <main className="cx-document">
        <section className="cx-kpis four">
          <article className="cx-kpi signal"><span className="mono">TOTAL SUBSYSTEMS</span><strong>{counts.total}</strong><small className="mono">OAUTH CLIENTS</small></article>
          <article className="cx-kpi"><span className="mono">ACTIVE</span><strong>{counts.active}</strong><small className="mono">SERVICE READY</small></article>
          <article className="cx-kpi"><span className="mono">PENDING</span><strong>{counts.pending}</strong><small className="mono">REVIEW REQUIRED</small></article>
          <article className="cx-kpi danger"><span className="mono">SUSPENDED</span><strong>{counts.suspended}</strong><small className="mono">ACCESS DISABLED</small></article>
        </section>
        {msg && <div className={`cx-alert ${msg.kind === "err" ? "danger" : ""}`}>{msg.text}</div>}
        <section className="cx-panel">
          <header><div><span className="mono">SERVICE REGISTRY</span><h2>ระบบย่อยทั้งหมด</h2></div><span className="cx-data">{shown.length} / {subs.length} SERVICES</span></header>
          <div className="cx-toolbar">
            <label><SearchIcon /><input value={q} onChange={(event) => setQ(event.target.value)} placeholder="ชื่อระบบ, Client ID หรือเจ้าของ..." /></label>
            <select value={filter} onChange={(event) => setFilter(event.target.value)}><option value="">ทุกสถานะ</option><option value="pending">pending</option><option value="active">active</option><option value="suspended">suspended</option></select>
            <select value={sort} onChange={(event) => setSort(event.target.value as "name" | "newest")}><option value="name">เรียงตามชื่อ</option><option value="newest">สร้างล่าสุด</option></select>
          </div>
          <div className="cx-service-grid">
            {shown.length === 0 && <div className="cx-empty"><strong>ไม่มีระบบย่อย</strong><span className="mono">NO REGISTERED SERVICES</span></div>}
            {shown.map((service) => {
              const health = service.health?.status || "unknown";
              const healthTone = ["online", "healthy"].includes(health) ? "" : health === "degraded" ? "warn" : health === "down" ? "danger" : "info";
              return <article key={service.id} className="cx-service-card">
                <header><i className={`cx-dot ${healthTone}`}><i /></i><div><Link href={`/subsystems/${service.id}`}>{service.name}</Link><code>{service.client_id}</code></div><span className={`cx-chip ${service.status === "active" ? "signal" : service.status === "pending" ? "warn" : "danger"}`}>{service.status}</span></header>
                <p>{service.description || "ไม่มีคำอธิบายระบบ"}</p>
                <dl>
                  <div><dt>OWNER</dt><dd>{service.owner_email || "—"}</dd></div>
                  <div><dt>ACCESS POLICY</dt><dd>{service.access_policy || "explicit"}</dd></div>
                  <div><dt>WHITELIST</dt><dd className="mono">{service.whitelist_count}</dd></div>
                  <div><dt>HEALTH</dt><dd className="mono">{health}{service.health?.latency_ms != null ? ` · ${service.health.latency_ms}ms` : ""}</dd></div>
                </dl>
                <footer><Link href={`/subsystems/${service.id}`}>ดูรายละเอียด →</Link>{service.status === "pending" && <div><button disabled={busy === service.id + "approve"} onClick={() => act(service.id, "approve")}>อนุมัติ</button><button disabled={busy === service.id + "reject"} onClick={() => act(service.id, "reject")}>ปฏิเสธ</button></div>}</footer>
              </article>;
            })}
          </div>
        </section>
      </main>
    </>
  );
}

function SearchIcon() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg> }
