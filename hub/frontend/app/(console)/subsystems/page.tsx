"use client";

import { useEffect, useState } from "react";
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

export default function SubsystemsPage() {
  const [subs, setSubs] = useState<Subsystem[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(
    null
  );

  function load() {
    const qs = filter ? `?status=${filter}` : "";
    clientFetch<Subsystem[]>(`/admin/subsystems${qs}`)
      .then(setSubs)
      .catch((e) => setMsg({ kind: "err", text: e.detail || "โหลดไม่สำเร็จ" }));
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [filter]);

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

  const columns: Column<Subsystem>[] = [
    {
      key: "name",
      header: "ระบบย่อย",
      render: (s) => (
        <div>
          <div className="font-semibold text-ink-900">{s.name}</div>
          <div className="text-xs text-ink-500 font-mono">{s.client_id}</div>
          {s.description && (
            <div className="text-xs text-ink-400 mt-0.5">{s.description}</div>
          )}
        </div>
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
      key: "whitelist_count",
      header: "Whitelist",
      render: (s) => (
        <span className="font-mono text-sm">{s.whitelist_count}</span>
      ),
    },
    {
      key: "owner_email",
      header: "เจ้าของ",
      render: (s) => (
        <span className="text-xs">{s.owner_email || "—"}</span>
      ),
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
        <div className="mb-5 flex items-center gap-2">
          {[
            ["", "ทั้งหมด"],
            ["pending", "รออนุมัติ"],
            ["active", "active"],
            ["suspended", "suspended"],
          ].map(([val, label]) => (
            <button
              key={val}
              onClick={() => setFilter(val)}
              className={
                "px-3 py-1.5 rounded-lg text-sm font-medium transition " +
                (filter === val
                  ? "bg-ink-900 text-white"
                  : "bg-white text-ink-600 border border-ink-200 hover:bg-ink-50")
              }
            >
              {label}
            </button>
          ))}
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

        <DataTable columns={columns} rows={subs} emptyMessage="ไม่มีระบบย่อย" />
      </main>
    </>
  );
}
