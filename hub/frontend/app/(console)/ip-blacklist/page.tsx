"use client";

import { useEffect, useState, useCallback } from "react";
import { Topbar } from "@/components/Topbar";
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
      <Topbar title="IP Blacklist" actions={<div className="cx-command-actions"><button className="cx-button" onClick={() => document.getElementById("new-blacklist-ip")?.focus()}>+ เพิ่ม IP</button><button className="cx-button" onClick={handleRefreshIpsum} disabled={refreshBusy}>{refreshBusy ? "กำลังอัปเดต…" : "Refresh IPSUM"}</button></div>} />
      <main className="cx-document signal-page signal-page-compact">
        {error && <div className="cx-alert danger">{error}</div>}
        {msg && <div className={`cx-alert ${msg.kind === "err" ? "danger" : ""}`}>{msg.text}</div>}
        <section className="cx-kpis three">
          <div className="cx-kpi"><i/><span>BLOCKED IPS</span><strong>{total.toLocaleString("en-US")}</strong><small>ทั้งหมดใน deny list</small></div>
          <div className="cx-kpi"><i/><span>VISIBLE RESULTS</span><strong>{entries.length}</strong><small>{search ? `ค้นหา ${search}` : `หน้า ${page + 1}`}</small></div>
          <div className="cx-kpi"><i/><span>IPSUM FEED</span><strong>{refreshBusy ? "SYNC" : "READY"}</strong><small>threat intelligence</small></div>
        </section>
        <section className="cx-grid upload-layout">
          <article className="cx-panel">
            <header><div><span className="mono">DENY LIST</span><h2>รายการ IP ที่ถูกบล็อก</h2></div></header>
            <div className="cx-toolbar"><form onSubmit={(e) => { e.preventDefault(); applySearch(); }}><span>⌕</span><input value={searchDraft} onChange={(e) => setSearchDraft(e.target.value)} placeholder="ค้นหา IP หรือเหตุผล"/><button type="submit">ค้นหา</button>{search && <button type="button" onClick={clearSearch}>ล้าง</button>}</form></div>
            <div className="cx-table-wrap"><table><thead>
                  <tr>
                    <th>IP ADDRESS</th><th>SOURCE / REASON</th><th>ADDED BY</th><th>ADDED AT</th><th>ACTIONS</th>
                  </tr>
                </thead><tbody>
                  {entries.length === 0 ? (
                    <tr><td colSpan={5}><div className="cx-empty"><b>ยังไม่มี IP ใน blacklist</b><small>No denied addresses</small></div></td></tr>
                  ) : (
                    entries.map((e) => (
                      <tr key={e.id}><td><b className="mono">{e.ip_address}</b></td><td>{e.reason || "—"}</td><td><code>{e.added_by || "SYSTEM"}</code></td><td><code>{e.created_at ? new Date(e.created_at).toISOString().slice(0,19).replace("T"," ") : "—"}</code></td><td><button className="cx-row-button danger" onClick={() => handleDelete(e.id, e.ip_address)}>ลบ</button></td>
                      </tr>
                    ))
                  )}
                </tbody></table></div>
            {total > PAGE_SIZE && (
              <div className="cx-pagination"><button onClick={() => setPage((p) => Math.max(0,p-1))} disabled={page === 0}>ก่อนหน้า</button><span className="mono">PAGE {page + 1} / {Math.max(1,Math.ceil(total/PAGE_SIZE))}</span><button onClick={() => setPage((p) => p+1)} disabled={(page+1)*PAGE_SIZE >= total}>ถัดไป</button></div>
            )}
          </article>
          <aside className="cx-panel"><header><div><span className="mono">BULK OPERATIONS</span><h2>เพิ่มและนำเข้ารายการ</h2></div></header><form className="cx-blacklist-add" onSubmit={handleAdd}><label>IP ADDRESS<input id="new-blacklist-ip" value={newIp} onChange={(e) => setNewIp(e.target.value)} placeholder="192.168.1.100"/></label><label>REASON<input value={newReason} onChange={(e) => setNewReason(e.target.value)} placeholder="เหตุผล (ไม่บังคับ)"/></label><button disabled={addBusy || !newIp.trim()}>{addBusy ? "กำลังเพิ่ม…" : "เพิ่มเข้ารายการ"}</button></form><div className="cx-drop"><b>อัปโหลดรายการ IP</b><span className="mono">CSV · ip,reason</span><label className="cx-button">{uploadBusy ? "กำลังอัปโหลด…" : "เลือกไฟล์"}<input type="file" accept=".csv" onChange={handleUpload} disabled={uploadBusy} hidden/></label>{uploadMsg && <small>{uploadMsg}</small>}</div></aside>
        </section>
      </main>
    </>
  );
}
