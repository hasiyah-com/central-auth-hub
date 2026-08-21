"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge } from "@/components/Badge";
import { clientFetch } from "@/lib/api";

type Subsystem = {
  id: string;
  name: string;
  description?: string;
  client_id: string;
  status: string;
  scope?: string;
  access_policy?: string;
  whitelist_count: number;
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

// นโยบายการเข้าถึง — ป้ายเดียวกับของเดิม
const POLICY_META: Record<string, { label: string; cls: string }> = {
  explicit: { label: "📋 รายชื่อ", cls: "bg-ink-100 text-ink-600" },
  all: { label: "🌐 ทุกคน", cls: "bg-sky-100 text-sky-700" },
  role: { label: "👥 บทบาท", cls: "bg-violet-100 text-violet-700" },
  attribute: { label: "🎯 คุณสมบัติ", cls: "bg-amber-100 text-amber-800" },
};

function policyOf(s: Subsystem) {
  return POLICY_META[s.access_policy || "explicit"] || POLICY_META.explicit;
}

/** KPI ด้านบน — สรุปยอดจาก status ของรายการทั้งหมด (ไม่ใช่ข้อมูลใหม่) */
function KpiCard({
  icon,
  label,
  value,
  total,
  tone,
  showPct,
}: {
  icon: string;
  label: string;
  value: number;
  total: number;
  tone: "brand" | "good" | "warn" | "danger";
  showPct?: boolean;
}) {
  const toneCls = {
    brand: "bg-brand-50 text-brand-600",
    good: "bg-emerald-50 text-emerald-600",
    warn: "bg-amber-50 text-amber-600",
    danger: "bg-rose-50 text-rose-600",
  }[tone];
  const pct = total > 0 ? Math.round((value / total) * 1000) / 10 : 0;
  return (
    <div className="bg-white rounded-xl border border-ink-200 shadow-sm p-4 flex items-center gap-4">
      <div
        className={`w-12 h-12 rounded-xl grid place-items-center text-xl shrink-0 ${toneCls}`}
      >
        {icon}
      </div>
      <div className="min-w-0">
        <div className="text-xs text-ink-500 truncate">{label}</div>
        <div className="text-2xl font-extrabold text-ink-900 tabular-nums leading-tight">
          {value}
        </div>
        <div className="text-[11px] text-ink-400">
          ระบบ{showPct && total > 0 ? ` (${pct}%)` : ""}
        </div>
      </div>
    </div>
  );
}

export default function SubsystemsPage() {
  const [subs, setSubs] = useState<Subsystem[]>([]);
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

  const counts = useMemo(
    () => ({
      total: subs.length,
      active: subs.filter((s) => s.status === "active").length,
      pending: subs.filter((s) => s.status === "pending").length,
      suspended: subs.filter((s) => s.status === "suspended").length,
    }),
    [subs]
  );

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    let rows = subs.filter((s) => !filter || s.status === filter);
    if (needle) {
      rows = rows.filter((s) =>
        [s.name, s.client_id, s.owner_email, s.description]
          .filter(Boolean)
          .some((v) => String(v).toLowerCase().includes(needle))
      );
    }
    return [...rows].sort((a, b) =>
      sort === "name"
        ? a.name.localeCompare(b.name, "th")
        : String(b.created_at || "").localeCompare(String(a.created_at || ""))
    );
  }, [subs, filter, q, sort]);

  const columns: Column<Subsystem>[] = [
    {
      key: "name",
      header: "ระบบย่อย",
      render: (s) => (
        <a
          href={`/subsystems/${s.id}`}
          className="block hover:bg-ink-50 -mx-2 px-2 py-1 rounded transition group"
        >
          <div className="font-semibold text-ink-900 group-hover:underline">
            {s.name}
          </div>
          <div className="text-xs text-ink-500 font-mono">{s.client_id}</div>
          {s.description && (
            <div className="text-xs text-ink-400 mt-0.5">{s.description}</div>
          )}
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
      render: (s) => {
        const m = policyOf(s);
        return (
          <span
            className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold ${m.cls}`}
          >
            {m.label}
          </span>
        );
      },
    },
    {
      key: "whitelist_count",
      header: "Whitelist",
      render: (s) => (
        <span className="font-mono text-sm">{s.whitelist_count}</span>
      ),
    },
    {
      key: "owner_email",
      header: "เจ้าของ",
      render: (s) => <span className="text-xs">{s.owner_email || "—"}</span>,
    },
    {
      key: "actions",
      header: "การกระทำ",
      width: "180px",
      render: (s) =>
        s.status === "pending" ? (
          <div className="flex gap-2">
            <button
              onClick={() => act(s.id, "approve")}
              disabled={busy === s.id + "approve"}
              className="px-3 py-1 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold disabled:opacity-50"
            >
              อนุมัติ
            </button>
            <button
              onClick={() => act(s.id, "reject")}
              disabled={busy === s.id + "reject"}
              className="px-3 py-1 rounded-md bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold disabled:opacity-50"
            >
              ปฏิเสธ
            </button>
          </div>
        ) : (
          <span className="text-xs text-ink-400">—</span>
        ),
    },
  ];

  return (
    <>
      <Topbar title="ระบบย่อย" />
      <main className="p-8 max-w-7xl mx-auto w-full">
        {/* ── หัวเรื่อง ────────────────────────────── */}
        <div className="flex items-start justify-between gap-4 flex-wrap mb-6">
          <div>
            <h2 className="text-2xl font-extrabold text-ink-900">
              จัดการระบบย่อย
            </h2>
            <p className="mt-1 text-sm text-ink-500">
              จัดการ OAuth Client และสิทธิ์การเข้าถึงของแต่ละระบบย่อย
            </p>
          </div>
          <Link
            href="/subsystems/pending"
            className="px-4 py-2 rounded-lg text-sm font-semibold bg-brand-600 hover:bg-brand-700 text-white transition"
          >
            หน้าอนุมัติแบบละเอียด →
          </Link>
        </div>

        {/* ── KPI (สรุปยอดจาก status) ──────────────── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <KpiCard
            icon="🧩"
            label="ทั้งหมด"
            value={counts.total}
            total={counts.total}
            tone="brand"
          />
          <KpiCard
            icon="✅"
            label="ใช้งานอยู่ (active)"
            value={counts.active}
            total={counts.total}
            tone="good"
            showPct
          />
          <KpiCard
            icon="⏳"
            label="รออนุมัติ (pending)"
            value={counts.pending}
            total={counts.total}
            tone="warn"
            showPct
          />
          <KpiCard
            icon="⛔"
            label="ถูกระงับ (suspended)"
            value={counts.suspended}
            total={counts.total}
            tone="danger"
            showPct
          />
        </div>

        {/* ── ค้นหา / กรอง / เรียง / สลับมุมมอง ────── */}
        <div className="bg-white rounded-xl border border-ink-200 shadow-sm p-4 mb-5 flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[220px]">
            <label className="block text-[11px] font-bold text-ink-400 uppercase tracking-wider mb-1.5">
              ค้นหา
            </label>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="ชื่อระบบ / client_id / เจ้าของ"
              className="w-full px-3 py-2 rounded-lg border border-ink-200 bg-white text-sm focus:outline-none focus:border-brand-500"
            />
          </div>
          <div>
            <label className="block text-[11px] font-bold text-ink-400 uppercase tracking-wider mb-1.5">
              สถานะ
            </label>
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="px-3 py-2 rounded-lg border border-ink-200 bg-white text-sm focus:outline-none focus:border-brand-500"
            >
              <option value="">ทั้งหมด</option>
              <option value="pending">รออนุมัติ</option>
              <option value="active">active</option>
              <option value="suspended">suspended</option>
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-bold text-ink-400 uppercase tracking-wider mb-1.5">
              เรียงตาม
            </label>
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as "name" | "newest")}
              className="px-3 py-2 rounded-lg border border-ink-200 bg-white text-sm focus:outline-none focus:border-brand-500"
            >
              <option value="name">ชื่อ (ก-ฮ)</option>
              <option value="newest">สร้างล่าสุด</option>
            </select>
          </div>
          <div className="flex gap-1 rounded-lg border border-ink-200 p-1">
            {(
              [
                ["grid", "▦", "การ์ด"],
                ["list", "☰", "ตาราง"],
              ] as const
            ).map(([v, icon, title]) => (
              <button
                key={v}
                onClick={() => setView(v)}
                title={title}
                className={
                  "px-3 py-1.5 rounded text-sm font-semibold transition " +
                  (view === v
                    ? "bg-brand-600 text-white"
                    : "text-ink-500 hover:bg-ink-50")
                }
              >
                {icon}
              </button>
            ))}
          </div>
        </div>

        {msg && (
          <div
            className={
              "mb-5 p-3 rounded-lg text-sm " +
              (msg.kind === "ok"
                ? "bg-emerald-50 border border-emerald-200 text-emerald-700"
                : "bg-rose-50 border border-rose-200 text-rose-700")
            }
          >
            {msg.text}
          </div>
        )}

        {/* ── มุมมองการ์ด / ตาราง ──────────────────── */}
        {view === "grid" ? (
          shown.length === 0 ? (
            <div className="bg-white rounded-xl border border-ink-200 p-10 text-center text-ink-400 text-sm">
              ไม่มีระบบย่อย
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {shown.map((s) => {
                const m = policyOf(s);
                return (
                  <div
                    key={s.id}
                    className="bg-white rounded-xl border border-ink-200 shadow-sm hover:shadow-md hover:border-brand-200 transition flex flex-col"
                  >
                    {/* หัวการ์ด */}
                    <Link
                      href={`/subsystems/${s.id}`}
                      className="p-5 pb-4 flex items-start gap-3 group"
                    >
                      <div className="w-11 h-11 rounded-xl bg-brand-50 grid place-items-center text-xl shrink-0">
                        🧩
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="font-bold text-ink-900 group-hover:underline truncate">
                          {s.name}
                        </div>
                        <div className="mt-1">
                          <Badge tone={STATUS_TONE[s.status] || "default"}>
                            {s.status}
                          </Badge>
                        </div>
                      </div>
                    </Link>

                    {/* รายละเอียด — field เดิมทั้งหมด */}
                    <div className="px-5 pb-4 space-y-2 border-t border-ink-100 pt-4">
                      {s.description && (
                        <p className="text-xs text-ink-500 line-clamp-2">
                          {s.description}
                        </p>
                      )}
                      <div className="flex justify-between gap-3">
                        <span className="text-xs text-ink-400">เจ้าของ</span>
                        <span className="text-xs font-medium text-ink-700 truncate">
                          {s.owner_email || "—"}
                        </span>
                      </div>
                      <div className="flex justify-between gap-3">
                        <span className="text-xs text-ink-400">Client ID</span>
                        <span className="text-xs font-mono text-ink-700 truncate">
                          {s.client_id}
                        </span>
                      </div>
                      <div className="flex justify-between gap-3 items-center">
                        <span className="text-xs text-ink-400">นโยบาย</span>
                        <span
                          className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${m.cls}`}
                        >
                          {m.label}
                        </span>
                      </div>
                      <div className="flex justify-between gap-3">
                        <span className="text-xs text-ink-400">Whitelist</span>
                        <span className="text-xs font-mono font-semibold text-ink-900">
                          {s.whitelist_count} คน
                        </span>
                      </div>
                    </div>

                    {/* การกระทำ — เฉพาะ pending เหมือนเดิม */}
                    {s.status === "pending" && (
                      <div className="px-5 py-3 border-t border-ink-100 flex gap-2">
                        <button
                          onClick={() => act(s.id, "approve")}
                          disabled={busy === s.id + "approve"}
                          className="flex-1 px-3 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold disabled:opacity-50"
                        >
                          อนุมัติ
                        </button>
                        <button
                          onClick={() => act(s.id, "reject")}
                          disabled={busy === s.id + "reject"}
                          className="flex-1 px-3 py-1.5 rounded-md bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold disabled:opacity-50"
                        >
                          ปฏิเสธ
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )
        ) : (
          <DataTable
            columns={columns}
            rows={shown}
            emptyMessage="ไม่มีระบบย่อย"
          />
        )}

        <div className="mt-4 text-xs text-ink-400">
          แสดง {shown.length} จาก {subs.length} รายการ
        </div>
      </main>
    </>
  );
}
