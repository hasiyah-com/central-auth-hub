"use client";

import { useEffect, useState, useCallback } from "react";
import { Topbar } from "@/components/Topbar";
import { StatsCard } from "@/components/StatsCard";
import { Badge } from "@/components/Badge";
import { clientFetch } from "@/lib/api";

type IpEntry = {
  id: string;
  ip_address: string;
  reason: string | null;
  added_by: string | null;
  created_at: string | null;
};

type ListResponse = {
  data: IpEntry[];
  total: number;
  skip: number;
  limit: number;
};

type IpsumResult = {
  ok: boolean;
  fetched?: number;
  new_inserted?: number;
  skipped_existing?: number;
  elapsed_sec?: number;
  error?: string;
};

const PAGE_SIZE = 50;

export default function IpBlacklistPage() {
  const [entries, setEntries] = useState<IpEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [searchDraft, setSearchDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Add form
  const [newIp, setNewIp] = useState("");
  const [newReason, setNewReason] = useState("");
  const [addBusy, setAddBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  // Upload
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);

  // Refresh ipsum
  const [refreshBusy, setRefreshBusy] = useState(false);

  const load = useCallback(() => {
    setError(null);
    const qs = new URLSearchParams({
      skip: String(page * PAGE_SIZE),
      limit: String(PAGE_SIZE),
    });
    if (search.trim()) qs.set("search", search.trim());
    clientFetch<ListResponse>(`/admin/ip-blacklist?${qs.toString()}`)
      .then((res) => {
        setEntries(res.data);
        setTotal(res.total);
      })
      .catch((e) => setError(e.detail || "โหลดข้อมูลไม่สำเร็จ"));
  }, [page, search]);

  useEffect(load, [load]);

  async function handleRefreshIpsum() {
    if (
      !confirm(
        "Refresh ipsum feed ตอนนี้?\n\n" +
          "ระบบจะดาวน์โหลด threat-intel L5 ล่าสุดจาก GitHub แล้ว upsert ลง DB"
      )
    )
      return;
    setRefreshBusy(true);
    setMsg(null);
    try {
      const r = await clientFetch<IpsumResult>(
        "/admin/ip-blacklist/refresh-ipsum",
        { method: "POST" }
      );
      if (r.ok) {
        setMsg({
          kind: "ok",
          text:
            `✓ Refresh สำเร็จ — fetched ${r.fetched}, ` +
            `เพิ่มใหม่ ${r.new_inserted}, ซ้ำ ${r.skipped_existing} ` +
            `(${r.elapsed_sec}s)`,
        });
        load();
      } else {
        setMsg({ kind: "err", text: `Refresh fail: ${r.error}` });
      }
    } catch (e) {
      const err = e as { detail?: string };
      setMsg({ kind: "err", text: err.detail || "refresh ไม่สำเร็จ" });
    } finally {
      setRefreshBusy(false);
    }
  }

  function applySearch() {
    setPage(0);
    setSearch(searchDraft);
  }
  function clearSearch() {
    setSearchDraft("");
    setSearch("");
    setPage(0);
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!newIp.trim()) return;
    setAddBusy(true);
    setMsg(null);
    try {
      await clientFetch("/admin/ip-blacklist", {
        method: "POST",
        body: JSON.stringify({ ip: newIp.trim(), reason: newReason.trim() || null }),
      });
      setMsg({ kind: "ok", text: `เพิ่ม ${newIp.trim()} สำเร็จ` });
      setNewIp("");
      setNewReason("");
      load();
    } catch (err) {
      const e = err as { detail?: string };
      setMsg({ kind: "err", text: e.detail || "เพิ่มไม่สำเร็จ" });
    } finally {
      setAddBusy(false);
    }
  }

  async function handleDelete(id: string, ip: string) {
    if (!confirm(`ลบ ${ip} ออกจาก blacklist?`)) return;
    try {
      await clientFetch(`/admin/ip-blacklist/${id}`, { method: "DELETE" });
      load();
    } catch {
      // silent
    }
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadBusy(true);
    setUploadMsg(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch("/api/proxy/admin/ip-blacklist/upload", {
        method: "POST",
        credentials: "include",
        body: formData,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw { detail: body.detail || res.statusText };
      }
      const data = await res.json();
      setUploadMsg(`เพิ่ม ${data.added} IP, ข้าม ${data.skipped} (ซ้ำ)`);
      load();
    } catch (err) {
      const ex = err as { detail?: string };
      setUploadMsg(ex.detail || "อัปโหลดไม่สำเร็จ");
    } finally {
      setUploadBusy(false);
      e.target.value = "";
    }
  }

  return (
    <>
      <Topbar title="IP Blacklist" />
      <main className="signal-page signal-page-compact">
        {/* Header */}
        <div className="mb-6 flex items-end justify-between gap-3 flex-wrap">
          <div>
            <h2 className="text-sm font-bold text-ink-500 uppercase tracking-wider">
              IP Blacklist Management
            </h2>
            <p className="text-xs text-ink-400 mt-1">
              {/* IP ที่อยู่ใน blacklist จะถูกตั้ง is_attack_ip = true อัตโนมัติตอน login
              (Wiefling 2022) */}
            </p>
          </div>
          <button
            onClick={handleRefreshIpsum}
            disabled={refreshBusy}
            className="px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-700 text-white text-sm font-semibold disabled:opacity-50 transition flex items-center gap-2"
            title="ดาวน์โหลด ipsum L5 ล่าสุดจาก GitHub"
          >
            <span className={refreshBusy ? "animate-spin" : ""}>🔄</span>
            {refreshBusy ? "กำลัง refresh…" : "Refresh ipsum"}
          </button>
        </div>

        {error && (
          <div className="mb-4 p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm">
            {error}
          </div>
        )}

        {/* KPI */}
        <div className="mb-6">
          <StatsCard
            label="IPs in Blacklist"
            value={total.toLocaleString("en-US")}
            sub={
              search
                ? `แสดง ${entries.length} ที่ตรงกับ "${search}"`
                : "ตรวจจับอัตโนมัติเมื่อ login"
            }
            icon="🚫"
            tone={total > 0 ? "danger" : "good"}
          />
        </div>

        {/* Add form */}
        <section className="mb-6 bg-white rounded-xl border border-ink-200 shadow-sm p-5">
          <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
            เพิ่ม IP
          </h3>
          <form onSubmit={handleAdd} className="flex gap-3 flex-wrap">
            <input
              type="text"
              value={newIp}
              onChange={(e) => setNewIp(e.target.value)}
              placeholder="IP address (e.g. 192.168.1.100)"
              className="flex-1 min-w-[200px] px-3 py-2 rounded-lg border border-ink-200 text-sm font-mono focus:outline-none focus:border-brand-500"
            />
            <input
              type="text"
              value={newReason}
              onChange={(e) => setNewReason(e.target.value)}
              placeholder="เหตุผล (optional)"
              className="flex-1 min-w-[150px] px-3 py-2 rounded-lg border border-ink-200 text-sm focus:outline-none focus:border-brand-500"
            />
            <button
              type="submit"
              disabled={addBusy || !newIp.trim()}
              className="px-4 py-2 rounded-lg bg-rose-600 text-white text-sm font-semibold hover:bg-rose-700 disabled:opacity-40 transition"
            >
              {addBusy ? "กำลังเพิ่ม…" : "เพิ่ม"}
            </button>
          </form>

          {msg && (
            <div
              className={`mt-3 p-2 rounded-lg text-sm ${
                msg.kind === "ok"
                  ? "bg-emerald-50 border border-emerald-200 text-emerald-700"
                  : "bg-rose-50 border border-rose-200 text-rose-700"
              }`}
            >
              {msg.text}
            </div>
          )}

          {/* CSV Upload */}
          <div className="mt-4 pt-4 border-t border-ink-100">
            <div className="flex items-center gap-3">
              <label className="px-4 py-2 rounded-lg border border-ink-200 text-sm font-medium text-ink-600 hover:bg-ink-50 cursor-pointer transition">
                {uploadBusy ? "กำลังอัปโหลด…" : "อัปโหลด CSV"}
                <input
                  type="file"
                  accept=".csv"
                  onChange={handleUpload}
                  disabled={uploadBusy}
                  className="hidden"
                />
              </label>
              <span className="text-[11px] text-ink-400">
                format: ip,reason (1 IP ต่อบรรทัด)
              </span>
            </div>
            {uploadMsg && (
              <div className="mt-2 text-sm text-ink-600">{uploadMsg}</div>
            )}
          </div>
        </section>

        {/* IP list */}
        <section>
          <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
            <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider">
              รายการ · {total.toLocaleString("en-US")} IPs
              {search && (
                <span className="text-brand-700 normal-case ml-2">
                  · ค้นหา &quot;{search}&quot;
                </span>
              )}
            </h3>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                applySearch();
              }}
              className="flex items-center gap-2"
            >
              <input
                type="text"
                value={searchDraft}
                onChange={(e) => setSearchDraft(e.target.value)}
                placeholder="ค้นหา IP / reason"
                className="px-3 py-1.5 rounded-lg border border-ink-200 text-xs font-mono w-[200px] focus:outline-none focus:border-brand-500"
              />
              <button
                type="submit"
                className="px-3 py-1.5 rounded-lg bg-ink-900 hover:bg-ink-700 text-white text-xs font-semibold"
              >
                ค้นหา
              </button>
              {search && (
                <button
                  type="button"
                  onClick={clearSearch}
                  className="px-2 py-1.5 rounded-lg border border-ink-200 hover:bg-ink-50 text-xs text-ink-600"
                >
                  ✕
                </button>
              )}
            </form>
          </div>
          <div className="bg-white rounded-xl border border-ink-200 overflow-hidden shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-ink-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider">
                      IP Address
                    </th>
                    <th className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider">
                      Reason
                    </th>
                    <th className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider w-[170px]">
                      Added
                    </th>
                    <th className="px-4 py-3 text-right text-[11px] font-bold text-ink-500 uppercase tracking-wider w-[80px]">
                      Action
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-100">
                  {entries.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="px-4 py-12 text-center text-ink-400">
                        ยังไม่มี IP ใน blacklist
                      </td>
                    </tr>
                  ) : (
                    entries.map((e) => (
                      <tr key={e.id} className="hover:bg-ink-50/50 transition">
                        <td className="px-4 py-3">
                          <span className="font-mono font-bold text-ink-900">
                            {e.ip_address}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-ink-600">
                          {e.reason || <span className="text-ink-300">—</span>}
                        </td>
                        <td className="px-4 py-3">
                          <span className="font-mono text-[11px] text-ink-500">
                            {e.created_at
                              ? new Date(e.created_at)
                                  .toISOString()
                                  .slice(0, 19)
                                  .replace("T", " ")
                              : "—"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            onClick={() => handleDelete(e.id, e.ip_address)}
                            className="px-2 py-1 rounded text-xs font-medium text-rose-600 hover:bg-rose-50 transition"
                          >
                            ลบ
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination footer */}
            {total > PAGE_SIZE && (
              <div className="flex items-center justify-between gap-3 px-4 py-3 border-t border-ink-100 bg-ink-50/50 text-xs">
                <span className="text-ink-600 font-mono">
                  {page * PAGE_SIZE + 1}–
                  {Math.min((page + 1) * PAGE_SIZE, total)} / {total.toLocaleString("en-US")}
                </span>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setPage(0)}
                    disabled={page === 0}
                    className="px-2 py-1 rounded border border-ink-200 hover:bg-white disabled:opacity-40"
                    title="หน้าแรก"
                  >
                    ⏮
                  </button>
                  <button
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                    disabled={page === 0}
                    className="px-3 py-1 rounded border border-ink-200 hover:bg-white disabled:opacity-40 font-semibold"
                  >
                    ← ก่อนหน้า
                  </button>
                  <span className="text-ink-500 font-mono px-2">
                    หน้า {page + 1} / {Math.max(1, Math.ceil(total / PAGE_SIZE))}
                  </span>
                  <button
                    onClick={() => setPage((p) => p + 1)}
                    disabled={(page + 1) * PAGE_SIZE >= total}
                    className="px-3 py-1 rounded border border-ink-200 hover:bg-white disabled:opacity-40 font-semibold"
                  >
                    ถัดไป →
                  </button>
                  <button
                    onClick={() =>
                      setPage(Math.max(0, Math.ceil(total / PAGE_SIZE) - 1))
                    }
                    disabled={(page + 1) * PAGE_SIZE >= total}
                    className="px-2 py-1 rounded border border-ink-200 hover:bg-white disabled:opacity-40"
                    title="หน้าสุดท้าย"
                  >
                    ⏭
                  </button>
                </div>
              </div>
            )}
          </div>
        </section>
      </main>
    </>
  );
}
