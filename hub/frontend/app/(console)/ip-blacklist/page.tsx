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

type ListResponse = { data: IpEntry[]; total: number };

export default function IpBlacklistPage() {
  const [entries, setEntries] = useState<IpEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Add form
  const [newIp, setNewIp] = useState("");
  const [newReason, setNewReason] = useState("");
  const [addBusy, setAddBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  // Upload
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    clientFetch<ListResponse>("/admin/ip-blacklist")
      .then((res) => setEntries(res.data))
      .catch((e) => setError(e.detail || "โหลดข้อมูลไม่สำเร็จ"));
  }, []);

  useEffect(load, [load]);

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
      <main className="p-8 max-w-5xl mx-auto w-full">
        {/* Header */}
        <div className="mb-6">
          <h2 className="text-sm font-bold text-ink-500 uppercase tracking-wider">
            IP Blacklist Management
          </h2>
          <p className="text-xs text-ink-400 mt-1">
            IP ที่อยู่ใน blacklist จะถูกตั้ง is_attack_ip = true อัตโนมัติตอน login
            (Wiefling 2022)
          </p>
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
            value={String(entries.length)}
            sub="ตรวจจับอัตโนมัติเมื่อ login"
            icon="🚫"
            tone={entries.length > 0 ? "danger" : "good"}
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
          <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
            รายการ · {entries.length} IPs
          </h3>
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
          </div>
        </section>
      </main>
    </>
  );
}
