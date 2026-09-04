"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge } from "@/components/Badge";
import { clientFetch } from "@/lib/api";
// design system ที่ port จากดีไซน์ตัวจริง — .sc = ชุด cx-* ของหน้าคอนโซล
import "../../signal-room.css";
import "../../signal-console.css";

type Subsystem = {
  id: string;
  name: string;
  description?: string;
  client_id: string;
  status: string;
  scope?: string;
  access_policy?: string;
  whitelist_count: number;
  health?: {
    status: "online" | "healthy" | "degraded" | "down" | "unknown";
    latency_ms?: number;
    checked_at?: string;
    error?: string;
  } | null;
  owner_email?: string;
  created_at?: string;
  approved_at?: string;
  [k: string]: unknown;
};

const STATUS_TONE: Record<string, "good" | "warn" | "danger" | "default"> = {
  active: "good",
  pending: "warn",
  suspended: "danger",
};

// นโยบายการเข้าถึง — ข้อความล้วน ไม่มีไอคอน (แยกด้วยสีของ class)
const POLICY_META: Record<string, { label: string; key: string }> = {
  explicit: { label: "รายชื่อ", key: "explicit" },
  all: { label: "ทุกคน", key: "all" },
  role: { label: "บทบาท", key: "role" },
  attribute: { label: "คุณสมบัติ", key: "attribute" },
};

/** ป้ายสถานะ health ล่าสุด — backend ping /health ของ subsystem ทุก 5 นาที */
const HEALTH_META: Record<string, { label: string; cls: string }> = {
  online: { label: "ปกติ", cls: "up" },
  healthy: { label: "ปกติ", cls: "up" },
  degraded: { label: "ช้า", cls: "slow" },
  down: { label: "ล่ม", cls: "down" },
  unknown: { label: "ยังไม่ตรวจ", cls: "unknown" },
};

function HealthCell({ s }: { s: Subsystem }) {
  const h = s.health;
  if (!h)
    return (
      <span className="cx-health unknown">
        <i />
        ยังไม่ตรวจ
      </span>
    );
  const m = HEALTH_META[h.status] || HEALTH_META.unknown;
  return (
    <span
      className={`cx-health ${m.cls}`}
      title={h.error || (h.checked_at ? `ตรวจล่าสุด ${h.checked_at}` : undefined)}
    >
      <i />
      {m.label}
      {h.latency_ms != null && <em>{h.latency_ms}ms</em>}
    </span>
  );
}

function policyOf(s: Subsystem) {
  return POLICY_META[s.access_policy || "explicit"] || POLICY_META.explicit;
}

function PolicyTag({ s }: { s: Subsystem }) {
  const m = policyOf(s);
  return <span className={`cx-tag ${m.key}`}>{m.label}</span>;
}

export default function SubsystemsPage() {
  const [subs, setSubs] = useState<Subsystem[] | null>(null);
  const [filter, setFilter] = useState<string>("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"name" | "newest">("name");
  const [view, setView] = useState<"grid" | "list">("grid");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(
    null
  );

  // โหลดทั้งหมดครั้งเดียว แล้วกรองฝั่ง client — KPI จะได้นับยอดจริงครบทุกสถานะ
  function load() {
    clientFetch<Subsystem[]>("/admin/subsystems")
      .then(setSubs)
      .catch((e) => setMsg({ kind: "err", text: e.detail || "โหลดไม่สำเร็จ" }));
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, []);

  async function act(id: string, action: "approve" | "reject") {
    setBusy(id + action);
    setMsg(null);
    try {
      const r = await clientFetch<{ message: string }>(
        `/admin/subsystems/${id}/${action}`,
        { method: "POST" }
      );
      setMsg({ kind: "ok", text: r.message });
      load();
    } catch (e) {
      const err = e as { detail?: string };
      setMsg({ kind: "err", text: err.detail || "ทำรายการไม่สำเร็จ" });
    } finally {
      setBusy(null);
    }
  }

  const rows = subs ?? [];

  const counts = useMemo(
    () => ({
      total: rows.length,
      active: rows.filter((s) => s.status === "active").length,
      pending: rows.filter((s) => s.status === "pending").length,
      suspended: rows.filter((s) => s.status === "suspended").length,
    }),
    [rows]
  );

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    let list = rows.filter((s) => !filter || s.status === filter);
    if (needle) {
      list = list.filter((s) =>
        [s.name, s.client_id, s.owner_email, s.description]
          .filter(Boolean)
          .some((v) => String(v).toLowerCase().includes(needle))
      );
    }
    return [...list].sort((a, b) =>
      sort === "name"
        ? a.name.localeCompare(b.name, "th")
        : String(b.created_at || "").localeCompare(String(a.created_at || ""))
    );
  }, [rows, filter, q, sort]);

  const columns: Column<Subsystem>[] = [
    {
      key: "name",
      header: "ระบบย่อย",
      render: (s) => (
        <a href={`/subsystems/${s.id}`} className="cx-row-link">
          <div className="font-semibold text-ink-900">{s.name}</div>
          <div className="cx-data">{s.client_id}</div>
          {s.description && <div className="cx-sub">{s.description}</div>}
        </a>
      ),
    },
    {
      key: "status",
      header: "สถานะ",
      render: (s) => (
        <Badge tone={STATUS_TONE[s.status] || "default"}>{s.status}</Badge>
      ),
    },
    {
      key: "access_policy",
      header: "นโยบาย",
      render: (s) => <PolicyTag s={s} />,
    },
    {
      key: "whitelist_count",
      header: "Whitelist",
      render: (s) => <span className="cx-data">{s.whitelist_count}</span>,
    },
    {
      key: "health",
      header: "Health ล่าสุด",
      render: (s) => <HealthCell s={s} />,
    },
    {
      key: "owner_email",
      header: "เจ้าของ",
      render: (s) => <span className="cx-data">{s.owner_email || "—"}</span>,
    },
    {
      key: "actions",
      header: "การกระทำ",
      width: "170px",
      render: (s) =>
        s.status === "pending" ? (
          <div className="flex gap-1.5">
            <button
              onClick={() => act(s.id, "approve")}
              disabled={busy === s.id + "approve"}
              className="cx-act ok"
            >
              อนุมัติ
            </button>
            <button
              onClick={() => act(s.id, "reject")}
              disabled={busy === s.id + "reject"}
              className="cx-act no"
            >
              ปฏิเสธ
            </button>
          </div>
        ) : (
          <span className="cx-sub">—</span>
        ),
    },
  ];

  // B51: subs === null คือ "ยังไม่โหลด" → KPI แสดง "—" ไม่ใช่ 0
  const pct = (v: number) =>
    counts.total > 0
      ? `${Math.round((v / counts.total) * 1000) / 10}% ของทั้งหมด`
      : "—";

  return (
    <div className="sc">
      <Topbar title="ระบบย่อย" />

      <section className="cx-command">
        <div>
          <span>
            <span className="cx-dot">
              <i />
            </span>
            control surface
          </span>
          <h1>Subsystems</h1>
        </div>
        <Link href="/subsystems/pending" className="cx-add-button">
          รายการรออนุมัติ
        </Link>
      </section>

      <main className="cx-document">
        {/* ── KPI — สรุปยอดจาก status ของรายการทั้งหมด ── */}
        <section className="cx-kpis four">
          {[
            {
              k: "total",
              label: "total",
              v: counts.total,
              sub: "OAuth client ที่ลงทะเบียน",
            },
            {
              k: "active",
              label: "active",
              v: counts.active,
              sub: pct(counts.active),
              tone: "signal",
            },
            {
              k: "pending",
              label: "pending",
              v: counts.pending,
              sub: pct(counts.pending),
              tone: "warn",
            },
            {
              k: "suspended",
              label: "suspended",
              v: counts.suspended,
              sub: pct(counts.suspended),
              tone: "danger",
            },
          ].map((c) => (
            <article key={c.k} className={`cx-kpi${c.tone ? " " + c.tone : ""}`}>
              <span>{c.label}</span>
              <strong className="mono">{subs === null ? "—" : c.v}</strong>
              <small className="mono">
                {subs === null ? "waiting for api" : c.sub}
              </small>
            </article>
          ))}
        </section>

        {msg && <div className={`cx-msg ${msg.kind}`}>{msg.text}</div>}

        {/* ── ทะเบียน OAuth client — ค้นหา / กรอง / เรียง / สลับมุมมอง ── */}
        <section className="cx-panel">
          <header>
            <div>
              <span>oauth client registry</span>
              <h2>All Subsystems</h2>
            </div>
            <span className="cx-chip mono">
              {subs === null ? "กำลังโหลด…" : `${shown.length} รายการ`}
            </span>
          </header>

          <div className="cx-toolbar">
            <label>
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                aria-hidden="true"
              >
                <circle cx="11" cy="11" r="7" />
                <path d="m20 20-3.5-3.5" />
              </svg>
              <input
                type="text"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="ชื่อระบบ / client id / เจ้าของ"
              />
            </label>

            <select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">ทุกสถานะ</option>
              <option value="pending">รออนุมัติ</option>
              <option value="active">active</option>
              <option value="suspended">suspended</option>
            </select>

            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as "name" | "newest")}
            >
              <option value="name">ชื่อ (ก-ฮ)</option>
              <option value="newest">สร้างล่าสุด</option>
            </select>

            {(q || filter) && (
              <button
                onClick={() => {
                  setQ("");
                  setFilter("");
                }}
                className="cx-chip"
              >
                ล้างตัวกรอง
              </button>
            )}

            <div className="cx-seg">
              {(
                [
                  ["grid", "การ์ด"],
                  ["list", "ตาราง"],
                ] as const
              ).map(([v, label]) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  className={view === v ? "on" : undefined}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {view === "list" ? (
            <div className="cx-table-wrap">
              <DataTable
                columns={columns}
                rows={shown}
                emptyMessage="ไม่มีระบบย่อย"
              />
            </div>
          ) : shown.length === 0 ? (
            <div className="cx-empty">
              <strong>{subs === null ? "กำลังโหลด…" : "ไม่มีระบบย่อย"}</strong>
            </div>
          ) : (
            <div className="p-3">
              <div className="cx-cards">
                {shown.map((s) => (
                  <article key={s.id} className={`cx-card ${s.status}`}>
                    <Link href={`/subsystems/${s.id}`}>
                      <b>{s.name}</b>
                      {s.description && <p>{s.description}</p>}
                      <span>
                        <Badge tone={STATUS_TONE[s.status] || "default"}>
                          {s.status}
                        </Badge>
                      </span>
                    </Link>

                    <dl>
                      <div>
                        <dt>เจ้าของ</dt>
                        <dd title={s.owner_email}>{s.owner_email || "—"}</dd>
                      </div>
                      <div>
                        <dt>client id</dt>
                        <dd className="mono" title={s.client_id}>
                          {s.client_id}
                        </dd>
                      </div>
                      <div>
                        <dt>นโยบาย</dt>
                        <dd>
                          <PolicyTag s={s} />
                        </dd>
                      </div>
                      <div>
                        <dt>whitelist</dt>
                        <dd className="num">{s.whitelist_count} คน</dd>
                      </div>
                      <div>
                        <dt>health ล่าสุด</dt>
                        <dd>
                          <HealthCell s={s} />
                        </dd>
                      </div>
                    </dl>

                    {s.status === "pending" && (
                      <footer>
                        <button
                          onClick={() => act(s.id, "approve")}
                          disabled={busy === s.id + "approve"}
                          className="cx-act ok"
                        >
                          อนุมัติ
                        </button>
                        <button
                          onClick={() => act(s.id, "reject")}
                          disabled={busy === s.id + "reject"}
                          className="cx-act no"
                        >
                          ปฏิเสธ
                        </button>
                      </footer>
                    )}
                  </article>
                ))}
              </div>
            </div>
          )}
        </section>

        <div className="cx-count">
          แสดง {shown.length} จาก {rows.length} รายการ
        </div>
      </main>
    </div>
  );
}
