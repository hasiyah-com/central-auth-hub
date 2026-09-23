// "use client";

// import { useEffect, useState, useCallback } from "react";
// import { Topbar } from "@/components/Topbar";
// import { StatsCard } from "@/components/StatsCard";
// import { Badge } from "@/components/Badge";
// import { clientFetch } from "@/lib/api";

// type IpEntry = {
//   id: string;
//   ip_address: string;
//   reason: string | null;
//   added_by: string | null;
//   created_at: string | null;
// };

// type ListResponse = {
//   data: IpEntry[];
//   total: number;
//   skip: number;
//   limit: number;
// };

// type IpsumResult = {
//   ok: boolean;
//   fetched?: number;
//   new_inserted?: number;
//   skipped_existing?: number;
//   elapsed_sec?: number;
//   error?: string;
// };

// const PAGE_SIZE = 50;

// export default function IpBlacklistPage() {
//   const [entries, setEntries] = useState<IpEntry[]>([]);
//   const [total, setTotal] = useState(0);
//   const [page, setPage] = useState(0);
//   const [search, setSearch] = useState("");
//   const [searchDraft, setSearchDraft] = useState("");
//   const [error, setError] = useState<string | null>(null);

//   // Add form
//   const [newIp, setNewIp] = useState("");
//   const [newReason, setNewReason] = useState("");
//   const [addBusy, setAddBusy] = useState(false);
//   const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

//   // Upload
//   const [uploadBusy, setUploadBusy] = useState(false);
//   const [uploadMsg, setUploadMsg] = useState<string | null>(null);

//   // Refresh ipsum
//   const [refreshBusy, setRefreshBusy] = useState(false);

//   const load = useCallback(() => {
//     setError(null);
//     const qs = new URLSearchParams({
//       skip: String(page * PAGE_SIZE),
//       limit: String(PAGE_SIZE),
//     });
//     if (search.trim()) qs.set("search", search.trim());
//     clientFetch<ListResponse>(`/admin/ip-blacklist?${qs.toString()}`)
//       .then((res) => {
//         setEntries(res.data);
//         setTotal(res.total);
//       })
//       .catch((e) => setError(e.detail || "โหลดข้อมูลไม่สำเร็จ"));
//   }, [page, search]);

//   useEffect(load, [load]);

//   async function handleRefreshIpsum() {
//     if (
//       !confirm(
//         "Refresh ipsum feed ตอนนี้?\n\n" +
//           "ระบบจะดาวน์โหลด threat-intel L5 ล่าสุดจาก GitHub แล้ว upsert ลง DB"
//       )
//     )
//       return;
//     setRefreshBusy(true);
//     setMsg(null);
//     try {
//       const r = await clientFetch<IpsumResult>(
//         "/admin/ip-blacklist/refresh-ipsum",
//         { method: "POST" }
//       );
//       if (r.ok) {
//         setMsg({
//           kind: "ok",
//           text:
//             `Refresh สำเร็จ — fetched ${r.fetched}, ` +
//             `เพิ่มใหม่ ${r.new_inserted}, ซ้ำ ${r.skipped_existing} ` +
//             `(${r.elapsed_sec}s)`,
//         });
//         load();
//       } else {
//         setMsg({ kind: "err", text: `Refresh fail: ${r.error}` });
//       }
//     } catch (e) {
//       const err = e as { detail?: string };
//       setMsg({ kind: "err", text: err.detail || "refresh ไม่สำเร็จ" });
//     } finally {
//       setRefreshBusy(false);
//     }
//   }

//   function applySearch() {
//     setPage(0);
//     setSearch(searchDraft);
//   }
//   function clearSearch() {
//     setSearchDraft("");
//     setSearch("");
//     setPage(0);
//   }

//   async function handleAdd(e: React.FormEvent) {
//     e.preventDefault();
//     if (!newIp.trim()) return;
//     setAddBusy(true);
//     setMsg(null);
//     try {
//       await clientFetch("/admin/ip-blacklist", {
//         method: "POST",
//         body: JSON.stringify({ ip: newIp.trim(), reason: newReason.trim() || null }),
//       });
//       setMsg({ kind: "ok", text: `เพิ่ม ${newIp.trim()} สำเร็จ` });
//       setNewIp("");
//       setNewReason("");
//       load();
//     } catch (err) {
//       const e = err as { detail?: string };
//       setMsg({ kind: "err", text: e.detail || "เพิ่มไม่สำเร็จ" });
//     } finally {
//       setAddBusy(false);
//     }
//   }

//   async function handleDelete(id: string, ip: string) {
//     if (!confirm(`ลบ ${ip} ออกจาก blacklist?`)) return;
//     try {
//       await clientFetch(`/admin/ip-blacklist/${id}`, { method: "DELETE" });
//       load();
//     } catch {
//       // silent
//     }
//   }

//   async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
//     const file = e.target.files?.[0];
//     if (!file) return;
//     setUploadBusy(true);
//     setUploadMsg(null);
//     try {
//       const formData = new FormData();
//       formData.append("file", file);
//       const res = await fetch("/api/proxy/admin/ip-blacklist/upload", {
//         method: "POST",
//         credentials: "include",
//         body: formData,
//       });
//       if (!res.ok) {
//         const body = await res.json().catch(() => ({ detail: res.statusText }));
//         throw { detail: body.detail || res.statusText };
//       }
//       const data = await res.json();
//       setUploadMsg(`เพิ่ม ${data.added} IP, ข้าม ${data.skipped} (ซ้ำ)`);
//       load();
//     } catch (err) {
//       const ex = err as { detail?: string };
//       setUploadMsg(ex.detail || "อัปโหลดไม่สำเร็จ");
//     } finally {
//       setUploadBusy(false);
//       e.target.value = "";
//     }
//   }

//   return (
//     <>
//       <Topbar title="IP Blacklist" />
//       <main className="p-8 max-w-5xl mx-auto w-full">
//         {/* Header */}
//         <div className="mb-6 flex items-end justify-between gap-3 flex-wrap">
//           <div>
//             <h2 className="text-sm font-bold text-ink-500 uppercase tracking-wider">
//               IP Blacklist Management
//             </h2>
//             <p className="text-xs text-ink-400 mt-1">
//               {/* IP ที่อยู่ใน blacklist จะถูกตั้ง is_attack_ip = true อัตโนมัติตอน login
//               (Wiefling 2022) */}
//             </p>
//           </div>
//           <button
//             onClick={handleRefreshIpsum}
//             disabled={refreshBusy}
//             className="px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-700 text-white text-sm font-semibold disabled:opacity-50 transition flex items-center gap-2"
//             title="ดาวน์โหลด ipsum L5 ล่าสุดจาก GitHub"
//           >
//             {refreshBusy ? "กำลัง refresh…" : "Refresh ipsum"}
//           </button>
//         </div>

//         {error && (
//           <div className="mb-4 p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm">
//             {error}
//           </div>
//         )}

//         {/* KPI */}
//         <div className="mb-6">
//           <StatsCard
//             label="IPs in Blacklist"
//             value={total.toLocaleString("en-US")}
//             sub={
//               search
//                 ? `แสดง ${entries.length} ที่ตรงกับ "${search}"`
//                 : "ตรวจจับอัตโนมัติเมื่อ login"
//             }
//             tone={total > 0 ? "danger" : "good"}
//           />
//         </div>

//         {/* Add form */}
//         <section className="mb-6 bg-white rounded-xl border border-ink-200 shadow-sm p-5">
//           <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
//             เพิ่ม IP
//           </h3>
//           <form onSubmit={handleAdd} className="flex gap-3 flex-wrap">
//             <input
//               type="text"
//               value={newIp}
//               onChange={(e) => setNewIp(e.target.value)}
//               placeholder="IP address (e.g. 192.168.1.100)"
//               className="flex-1 min-w-[200px] px-3 py-2 rounded-lg border border-ink-200 text-sm font-mono focus:outline-none focus:border-brand-500"
//             />
//             <input
//               type="text"
//               value={newReason}
//               onChange={(e) => setNewReason(e.target.value)}
//               placeholder="เหตุผล (optional)"
//               className="flex-1 min-w-[150px] px-3 py-2 rounded-lg border border-ink-200 text-sm focus:outline-none focus:border-brand-500"
//             />
//             <button
//               type="submit"
//               disabled={addBusy || !newIp.trim()}
//               className="px-4 py-2 rounded-lg bg-rose-600 text-white text-sm font-semibold hover:bg-rose-700 disabled:opacity-40 transition"
//             >
//               {addBusy ? "กำลังเพิ่ม…" : "เพิ่ม"}
//             </button>
//           </form>

//           {msg && (
//             <div
//               className={`mt-3 p-2 rounded-lg text-sm ${
//                 msg.kind === "ok"
//                   ? "bg-emerald-50 border border-emerald-200 text-emerald-700"
//                   : "bg-rose-50 border border-rose-200 text-rose-700"
//               }`}
//             >
//               {msg.text}
//             </div>
//           )}

//           {/* CSV Upload */}
//           <div className="mt-4 pt-4 border-t border-ink-100">
//             <div className="flex items-center gap-3">
//               <label className="px-4 py-2 rounded-lg border border-ink-200 text-sm font-medium text-ink-600 hover:bg-ink-50 cursor-pointer transition">
//                 {uploadBusy ? "กำลังอัปโหลด…" : "อัปโหลด CSV"}
//                 <input
//                   type="file"
//                   accept=".csv"
//                   onChange={handleUpload}
//                   disabled={uploadBusy}
//                   className="hidden"
//                 />
//               </label>
//               <span className="text-[11px] text-ink-400">
//                 format: ip,reason (1 IP ต่อบรรทัด)
//               </span>
//             </div>
//             {uploadMsg && (
//               <div className="mt-2 text-sm text-ink-600">{uploadMsg}</div>
//             )}
//           </div>
//         </section>

//         {/* IP list */}
//         <section>
//           <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
//             <h3 className="text-xs font-bold text-ink-500 uppercase tracking-wider">
//               รายการ · {total.toLocaleString("en-US")} IPs
//               {search && (
//                 <span className="text-brand-700 normal-case ml-2">
//                   · ค้นหา &quot;{search}&quot;
//                 </span>
//               )}
//             </h3>
//             <form
//               onSubmit={(e) => {
//                 e.preventDefault();
//                 applySearch();
//               }}
//               className="flex items-center gap-2"
//             >
//               <input
//                 type="text"
//                 value={searchDraft}
//                 onChange={(e) => setSearchDraft(e.target.value)}
//                 placeholder="ค้นหา IP / reason"
//                 className="px-3 py-1.5 rounded-lg border border-ink-200 text-xs font-mono w-[200px] focus:outline-none focus:border-brand-500"
//               />
//               <button
//                 type="submit"
//                 className="px-3 py-1.5 rounded-lg bg-ink-900 hover:bg-ink-700 text-white text-xs font-semibold"
//               >
//                 ค้นหา
//               </button>
//               {search && (
//                 <button
//                   type="button"
//                   onClick={clearSearch}
//                   className="px-2 py-1.5 rounded-lg border border-ink-200 hover:bg-ink-50 text-xs text-ink-600"
//                 >
//                   ล้าง
//                 </button>
//               )}
//             </form>
//           </div>
//           <div className="bg-white rounded-xl border border-ink-200 overflow-hidden shadow-sm">
//             <div className="overflow-x-auto">
//               <table className="w-full text-sm">
//                 <thead className="bg-ink-50">
//                   <tr>
//                     <th className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider">
//                       IP Address
//                     </th>
//                     <th className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider">
//                       Reason
//                     </th>
//                     <th className="px-4 py-3 text-left text-[11px] font-bold text-ink-500 uppercase tracking-wider w-[170px]">
//                       Added
//                     </th>
//                     <th className="px-4 py-3 text-right text-[11px] font-bold text-ink-500 uppercase tracking-wider w-[80px]">
//                       Action
//                     </th>
//                   </tr>
//                 </thead>
//                 <tbody className="divide-y divide-ink-100">
//                   {entries.length === 0 ? (
//                     <tr>
//                       <td colSpan={4} className="px-4 py-12 text-center text-ink-400">
//                         ยังไม่มี IP ใน blacklist
//                       </td>
//                     </tr>
//                   ) : (
//                     entries.map((e) => (
//                       <tr key={e.id} className="hover:bg-ink-50/50 transition">
//                         <td className="px-4 py-3">
//                           <span className="font-mono font-bold text-ink-900">
//                             {e.ip_address}
//                           </span>
//                         </td>
//                         <td className="px-4 py-3 text-ink-600">
//                           {e.reason || <span className="text-ink-300">—</span>}
//                         </td>
//                         <td className="px-4 py-3">
//                           <span className="font-mono text-[11px] text-ink-500">
//                             {e.created_at
//                               ? new Date(e.created_at)
//                                   .toISOString()
//                                   .slice(0, 19)
//                                   .replace("T", " ")
//                               : "—"}
//                           </span>
//                         </td>
//                         <td className="px-4 py-3 text-right">
//                           <button
//                             onClick={() => handleDelete(e.id, e.ip_address)}
//                             className="px-2 py-1 rounded text-xs font-medium text-rose-600 hover:bg-rose-50 transition"
//                           >
//                             ลบ
//                           </button>
//                         </td>
//                       </tr>
//                     ))
//                   )}
//                 </tbody>
//               </table>
//             </div>

//             {/* Pagination footer */}
//             {total > PAGE_SIZE && (
//               <div className="flex items-center justify-between gap-3 px-4 py-3 border-t border-ink-100 bg-ink-50/50 text-xs">
//                 <span className="text-ink-600 font-mono">
//                   {page * PAGE_SIZE + 1}–
//                   {Math.min((page + 1) * PAGE_SIZE, total)} / {total.toLocaleString("en-US")}
//                 </span>
//                 <div className="flex items-center gap-2">
//                   <button
//                     onClick={() => setPage(0)}
//                     disabled={page === 0}
//                     className="px-2 py-1 rounded border border-ink-200 hover:bg-white disabled:opacity-40"
//                     title="หน้าแรก"
//                   >

//                   </button>
//                   <button
//                     onClick={() => setPage((p) => Math.max(0, p - 1))}
//                     disabled={page === 0}
//                     className="px-3 py-1 rounded border border-ink-200 hover:bg-white disabled:opacity-40 font-semibold"
//                   >
//                     ← ก่อนหน้า
//                   </button>
//                   <span className="text-ink-500 font-mono px-2">
//                     หน้า {page + 1} / {Math.max(1, Math.ceil(total / PAGE_SIZE))}
//                   </span>
//                   <button
//                     onClick={() => setPage((p) => p + 1)}
//                     disabled={(page + 1) * PAGE_SIZE >= total}
//                     className="px-3 py-1 rounded border border-ink-200 hover:bg-white disabled:opacity-40 font-semibold"
//                   >
//                     ถัดไป →
//                   </button>
//                   <button
//                     onClick={() =>
//                       setPage(Math.max(0, Math.ceil(total / PAGE_SIZE) - 1))
//                     }
//                     disabled={(page + 1) * PAGE_SIZE >= total}
//                     className="px-2 py-1 rounded border border-ink-200 hover:bg-white disabled:opacity-40"
//                     title="หน้าสุดท้าย"
//                   >

//                   </button>
//                 </div>
//               </div>
//             )}
//           </div>
//         </section>
//       </main>
//     </>
//   );
// }

"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";
import styles from "./ip-blacklist.module.css";

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

type UploadResult = {
  added: number;
  skipped: number;
};

type Notice = {
  kind: "ok" | "err";
  text: string;
};

const PAGE_SIZE = 50;

export default function IpBlacklistPage() {
  const [entries, setEntries] = useState<IpEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [searchDraft, setSearchDraft] = useState("");

  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [deleteBusyId, setDeleteBusyId] = useState<string | null>(null);

  const [newIp, setNewIp] = useState("");
  const [newReason, setNewReason] = useState("");
  const [addBusy, setAddBusy] = useState(false);

  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadFileName, setUploadFileName] = useState("");
  const [uploadMessage, setUploadMessage] = useState("");

  const [refreshBusy, setRefreshBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);

    const query = new URLSearchParams({
      skip: String(page * PAGE_SIZE),
      limit: String(PAGE_SIZE),
    });

    if (search.trim()) {
      query.set("search", search.trim());
    }

    try {
      const response = await clientFetch<ListResponse>(
        "/admin/ip-blacklist?" + query.toString(),
      );
      setEntries(response.data);
      setTotal(response.total);
    } catch (error) {
      setNotice({
        kind: "err",
        text: getErrorMessage(error, "โหลดรายการ IP Blacklist ไม่สำเร็จ"),
      });
    } finally {
      setLoading(false);
    }
  }, [page, search]);

  useEffect(() => {
    void load();
  }, [load]);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const rangeStart = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const rangeEnd = Math.min((page + 1) * PAGE_SIZE, total);

  const sourceSummary = useMemo(() => {
    const visibleIpsum = entries.filter((entry) => getSource(entry) === "IPSUM").length;
    const visibleManual = entries.filter((entry) => getSource(entry) === "MANUAL").length;
    return { visibleIpsum, visibleManual };
  }, [entries]);

  function applySearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(0);
    setSearch(searchDraft.trim());
  }

  function clearSearch() {
    setSearchDraft("");
    setSearch("");
    setPage(0);
  }

  async function handleAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const ip = newIp.trim();
    if (!ip) {
      setNotice({ kind: "err", text: "กรุณาระบุ IP Address" });
      return;
    }

    setAddBusy(true);
    setNotice(null);

    try {
      await clientFetch("/admin/ip-blacklist", {
        method: "POST",
        body: JSON.stringify({
          ip,
          reason: newReason.trim() || null,
        }),
      });

      setNewIp("");
      setNewReason("");
      setPage(0);
      setNotice({ kind: "ok", text: "เพิ่ม " + ip + " เข้ารายการเรียบร้อยแล้ว" });

      if (page === 0) {
        await load();
      }
    } catch (error) {
      setNotice({
        kind: "err",
        text: getErrorMessage(error, "เพิ่ม IP ไม่สำเร็จ"),
      });
    } finally {
      setAddBusy(false);
    }
  }

  async function handleDelete(id: string, ip: string) {
    const confirmed = window.confirm(
      "นำ " + ip + " ออกจาก Blacklist?\n\nIP นี้จะไม่ถูกระบุเป็น Attack IP จากรายการนี้อีก",
    );
    if (!confirmed) return;

    setDeleteBusyId(id);
    setNotice(null);

    try {
      await clientFetch("/admin/ip-blacklist/" + encodeURIComponent(id), {
        method: "DELETE",
      });

      setNotice({ kind: "ok", text: "นำ " + ip + " ออกจากรายการแล้ว" });

      if (entries.length === 1 && page > 0) {
        setPage((current) => Math.max(0, current - 1));
      } else {
        await load();
      }
    } catch (error) {
      setNotice({
        kind: "err",
        text: getErrorMessage(error, "ลบ IP ไม่สำเร็จ"),
      });
    } finally {
      setDeleteBusyId(null);
    }
  }

  async function handleUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;

    setUploadBusy(true);
    setUploadFileName(file.name);
    setUploadMessage("");
    setNotice(null);

    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await fetch("/api/proxy/admin/ip-blacklist/upload", {
        method: "POST",
        credentials: "include",
        body: formData,
      });

      if (!response.ok) {
        const body = await response
          .json()
          .catch(() => ({ detail: response.statusText }));
        throw new Error(body.detail || response.statusText);
      }

      const result = (await response.json()) as UploadResult;
      const text =
        "เพิ่ม " +
        result.added.toLocaleString("en-US") +
        " IP · ข้ามรายการซ้ำ " +
        result.skipped.toLocaleString("en-US");

      setUploadMessage(text);
      setNotice({ kind: "ok", text: "นำเข้าไฟล์ " + file.name + " สำเร็จ — " + text });
      setPage(0);

      if (page === 0) {
        await load();
      }
    } catch (error) {
      const message = getErrorMessage(error, "อัปโหลด CSV ไม่สำเร็จ");
      setUploadMessage(message);
      setNotice({ kind: "err", text: message });
    } finally {
      setUploadBusy(false);
      event.target.value = "";
    }
  }

  async function handleRefreshIpsum() {
    const confirmed = window.confirm(
      "อัปเดต IPSUM Threat Feed ตอนนี้?\n\nระบบจะดาวน์โหลดรายการ L5 ล่าสุดและเพิ่มเฉพาะ IP ที่ยังไม่มีในฐานข้อมูล",
    );
    if (!confirmed) return;

    setRefreshBusy(true);
    setNotice(null);

    try {
      const result = await clientFetch<IpsumResult>(
        "/admin/ip-blacklist/refresh-ipsum",
        { method: "POST" },
      );

      if (!result.ok) {
        throw new Error(result.error || "IPSUM refresh failed");
      }

      const text =
        "อัปเดต IPSUM สำเร็จ · ดึง " +
        numberOrDash(result.fetched) +
        " · เพิ่มใหม่ " +
        numberOrDash(result.new_inserted) +
        " · ซ้ำ " +
        numberOrDash(result.skipped_existing) +
        (result.elapsed_sec == null ? "" : " · " + result.elapsed_sec + " วินาที");

      setNotice({ kind: "ok", text });
      setPage(0);

      if (page === 0) {
        await load();
      }
    } catch (error) {
      setNotice({
        kind: "err",
        text: getErrorMessage(error, "อัปเดต IPSUM ไม่สำเร็จ"),
      });
    } finally {
      setRefreshBusy(false);
    }
  }

  return (
    <>
      <Topbar title="IP Blacklist" />

      <main className={styles.page}>
        <section className={styles.hero}>
          <div>
            <span className={styles.eyebrow}>
              <span className={styles.pulse} aria-hidden="true" />
              NETWORK DEFENSE
            </span>
            <h1>ควบคุม IP ที่ถูกบล็อก</h1>
            <p>
              จัดการ Deny List จากผู้ดูแลและ Threat Intelligence โดยข้อมูลทุกส่วนเชื่อมกับ Backend จริง
            </p>
          </div>

          <div className={styles.heroActions}>
            <div className={styles.feedStatus}>
              <span className={styles.feedLabel}>IPSUM FEED</span>
              <strong>
                <span className={styles.pulse} aria-hidden="true" />
                {refreshBusy ? "SYNCING" : "READY"}
              </strong>
            </div>

            <button
              type="button"
              className={styles.syncButton}
              onClick={() => void handleRefreshIpsum()}
              disabled={refreshBusy}
            >
              <RefreshIcon spinning={refreshBusy} />
              {refreshBusy ? "กำลังอัปเดต…" : "อัปเดต IPSUM"}
            </button>
          </div>
        </section>

        {notice && (
          <div
            className={[
              styles.notice,
              notice.kind === "ok" ? styles.noticeOk : styles.noticeError,
            ].join(" ")}
            role="status"
          >
            <span aria-hidden="true">{notice.kind === "ok" ? "✓" : "!"}</span>
            <p>{notice.text}</p>
            <button type="button" onClick={() => setNotice(null)} aria-label="ปิดข้อความ">
              ×
            </button>
          </div>
        )}

        <section className={styles.metrics} aria-label="สรุป IP Blacklist">
          <Metric
            label="BLOCKED IPS"
            value={total.toLocaleString("en-US")}
            detail="ทั้งหมดใน Deny List"
          />
          <Metric
            label="VISIBLE RESULTS"
            value={loading ? "—" : entries.length.toLocaleString("en-US")}
            detail={search ? 'ผลการค้นหา "' + search + '"' : "หน้า " + (page + 1)}
          />
          <Metric
            label="CURRENT PAGE SOURCE"
            value={loading ? "—" : sourceSummary.visibleIpsum + " / " + sourceSummary.visibleManual}
            detail="IPSUM / MANUAL"
          />
        </section>

        <div className={styles.workspace}>
          <section className={styles.panel}>
            <header className={styles.panelHeader}>
              <div>
                <span className={styles.kicker}>DENY LIST</span>
                <h2>รายการ IP ที่ถูกบล็อก</h2>
              </div>
              <span className={styles.count}>
                {loading ? "LOADING" : total.toLocaleString("en-US") + " IPS"}
              </span>
            </header>

            <form className={styles.toolbar} onSubmit={applySearch}>
              <label className={styles.search}>
                <SearchIcon />
                <input
                  value={searchDraft}
                  onChange={(event) => setSearchDraft(event.target.value)}
                  placeholder="ค้นหา IP Address หรือเหตุผล"
                  aria-label="ค้นหา IP Address หรือเหตุผล"
                />
              </label>
              <button type="submit" className={styles.secondaryButton}>
                ค้นหา
              </button>
              {search && (
                <button type="button" className={styles.clearButton} onClick={clearSearch}>
                  ล้าง
                </button>
              )}
              <button
                type="button"
                className={styles.secondaryButton}
                onClick={() => void load()}
                disabled={loading}
              >
                รีเฟรช
              </button>
            </form>

            <div className={styles.tableScroll}>
              <table className={styles.table}>
                <thead className={styles.tableHead}>
                  <tr>
                    <th>IP ADDRESS</th>
                    <th>SOURCE / REASON</th>
                    <th>ADDED BY</th>
                    <th>ADDED AT</th>
                    <th>ACTION</th>
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    <LoadingRows />
                  ) : entries.length === 0 ? (
                    <tr>
                      <td colSpan={5}>
                        <div className={styles.empty}>
                          <div className={styles.emptyMark} aria-hidden="true">
                            <span />
                          </div>
                          <strong>
                            {search ? "ไม่พบ IP ที่ตรงกับคำค้น" : "ยังไม่มี IP ใน Blacklist"}
                          </strong>
                          <p>
                            {search
                              ? "ลองค้นหาด้วย IP บางส่วนหรือข้อความในเหตุผล"
                              : "เพิ่ม IP ด้วยแบบฟอร์มหรือนำเข้าจากไฟล์ CSV"}
                          </p>
                          {search && (
                            <button
                              type="button"
                              className={styles.secondaryButton}
                              onClick={clearSearch}
                            >
                              ล้างการค้นหา
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ) : (
                    entries.map((entry) => {
                      const source = getSource(entry);
                      return (
                        <tr key={entry.id}>
                          <td>
                            <div className={styles.ipCell}>
                              <span className={styles.blockMark} aria-hidden="true" />
                              <code>{entry.ip_address}</code>
                            </div>
                          </td>
                          <td>
                            <span className={styles.source}>{source}</span>
                            <div className={styles.reason}>{entry.reason || "ไม่มีคำอธิบาย"}</div>
                          </td>
                          <td>
                            <code className={styles.actor}>
                              {entry.added_by ? shortId(entry.added_by) : "SYSTEM"}
                            </code>
                          </td>
                          <td>
                            <time
                              className={styles.time}
                              dateTime={entry.created_at || undefined}
                            >
                              {formatDate(entry.created_at)}
                            </time>
                            <span className={styles.zone}>ASIA/BANGKOK</span>
                          </td>
                          <td className={styles.actionCell}>
                            <button
                              type="button"
                              className={styles.dangerButton}
                              disabled={deleteBusyId === entry.id}
                              onClick={() => void handleDelete(entry.id, entry.ip_address)}
                            >
                              {deleteBusyId === entry.id ? "กำลังลบ…" : "ลบ"}
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            {total > PAGE_SIZE && (
              <footer className={styles.pager}>
                <span className={styles.pageInfo}>
                  {rangeStart.toLocaleString("en-US")}–{rangeEnd.toLocaleString("en-US")} /{" "}
                  {total.toLocaleString("en-US")} · PAGE {page + 1} OF {pageCount}
                </span>
                <div className={styles.pagerActions}>
                  <button
                    type="button"
                    onClick={() => setPage(0)}
                    disabled={page === 0 || loading}
                    aria-label="หน้าแรก"
                  >
                    «
                  </button>
                  <button
                    type="button"
                    onClick={() => setPage((current) => Math.max(0, current - 1))}
                    disabled={page === 0 || loading}
                  >
                    ก่อนหน้า
                  </button>
                  <button
                    type="button"
                    onClick={() => setPage((current) => current + 1)}
                    disabled={(page + 1) * PAGE_SIZE >= total || loading}
                  >
                    ถัดไป
                  </button>
                  <button
                    type="button"
                    onClick={() => setPage(pageCount - 1)}
                    disabled={(page + 1) * PAGE_SIZE >= total || loading}
                    aria-label="หน้าสุดท้าย"
                  >
                    »
                  </button>
                </div>
              </footer>
            )}
          </section>

          <aside className={styles.controlPanel}>
            <section className={styles.panel}>
              <header className={styles.panelHeader}>
                <div>
                  <span className={styles.kicker}>BLOCK CONTROL</span>
                  <h2>เพิ่ม IP เข้ารายการ</h2>
                </div>
                <span className={styles.count}>ADMIN</span>
              </header>

              <form className={styles.form} onSubmit={handleAdd}>
                <label className={styles.field}>
                  <span className={styles.fieldLabel}>IP ADDRESS</span>
                  <input
                    id="new-blacklist-ip"
                    value={newIp}
                    onChange={(event) => setNewIp(event.target.value)}
                    placeholder="192.168.1.100"
                    autoComplete="off"
                  />
                </label>

                <label className={styles.field}>
                  <span className={styles.fieldLabel}>REASON · OPTIONAL</span>
                  <input
                    value={newReason}
                    onChange={(event) => setNewReason(event.target.value)}
                    placeholder="เช่น Brute force, Scanner"
                    autoComplete="off"
                  />
                </label>

                <button
                  type="submit"
                  className={styles.primaryButton}
                  disabled={addBusy || !newIp.trim()}
                >
                  {addBusy ? "กำลังเพิ่ม…" : "เพิ่มเข้ารายการ"}
                </button>
              </form>

              <div className={styles.divider}>OR BULK IMPORT</div>

              <div className={styles.upload}>
                <div className={styles.uploadIcon}>
                  <UploadIcon />
                </div>
                <strong>นำเข้ารายการจาก CSV</strong>
                <small>{uploadFileName || "รูปแบบ: ip,reason · Header ไม่บังคับ"}</small>
                <label className={styles.uploadButton}>
                  {uploadBusy ? "กำลังอัปโหลด…" : "เลือกไฟล์ CSV"}
                  <input
                    type="file"
                    accept=".csv,text/csv"
                    onChange={(event) => void handleUpload(event)}
                    disabled={uploadBusy}
                    hidden
                  />
                </label>
                {uploadMessage && <p className={styles.uploadMessage}>{uploadMessage}</p>}
              </div>
            </section>

            <section className={styles.policy}>
              <span>ENFORCEMENT</span>
              <strong>Exact IP Match</strong>
              <p>
                IP ในรายการจะถูกตั้งค่าเป็น Attack IP โดยอัตโนมัติระหว่างการประเมินความเสี่ยงตอน Login
              </p>
            </section>
          </aside>
        </div>
      </main>
    </>
  );
}

function Metric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <article className={styles.metric}>
      <span className={styles.metricLabel}>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function LoadingRows() {
  return (
    <>
      {[0, 1, 2].map((row) => (
        <tr key={row} className={styles.loadingRow}>
          {[0, 1, 2, 3, 4].map((cell) => (
            <td key={cell}>
              <div className={styles.skeleton} />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

function RefreshIcon({ spinning }: { spinning: boolean }) {
  return (
    <svg
      className={spinning ? styles.spin : undefined}
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path d="M20 7v5h-5M4 17v-5h5" />
      <path d="M18.4 9A7 7 0 0 0 6.2 6.2L4 9M5.6 15A7 7 0 0 0 17.8 17.8L20 15" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4 4" />
    </svg>
  );
}

function UploadIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 16V4m0 0L8 8m4-4 4 4" />
      <path d="M5 14v5h14v-5" />
    </svg>
  );
}

function getSource(entry: IpEntry) {
  const reason = (entry.reason || "").toLowerCase();
  if (!entry.added_by && reason.includes("ipsum")) return "IPSUM";
  if (entry.added_by) return "MANUAL";
  return "SYSTEM";
}

function shortId(value: string) {
  return value.length > 13 ? value.slice(0, 8) + "…" : value;
}

function numberOrDash(value: number | undefined) {
  return value == null ? "—" : value.toLocaleString("en-US");
}

function getErrorMessage(error: unknown, fallback: string) {
  if (typeof error === "object" && error !== null && "detail" in error) {
    const detail = (error as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
  }

  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function formatDate(value: string | null) {
  if (!value) return "—";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat("th-TH", {
    timeZone: "Asia/Bangkok",
    day: "2-digit",
    month: "short",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}