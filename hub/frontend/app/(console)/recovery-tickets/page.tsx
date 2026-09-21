"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Topbar } from "@/components/Topbar";
import {
  adminListRecoveryTickets,
  adminApproveTicket,
  adminRejectTicket,
  type RecoveryTicket,
} from "@/lib/passkey";
import "@/app/signal-room.css";
import "@/app/signal-console.css";

const EVIDENCE = [
  { v: "student_card", label: "บัตรนักศึกษา" },
  { v: "citizen_id", label: "บัตรประชาชน" },
  { v: "other", label: "อื่นๆ" },
];

type LevelFilter = "all" | "HIGH" | "NORMAL";

/* ── ไอคอนเส้น (โปรเจกต์ไม่ได้ติดตั้ง lucide) ─────────────────────────── */
function RIcon({ children, size = 14 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}
const IconRefresh = ({ size = 14 }: { size?: number }) => (
  <RIcon size={size}>
    <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
    <path d="M21 3v5h-5" />
    <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
    <path d="M3 21v-5h5" />
  </RIcon>
);
const IconKey = ({ size = 13 }: { size?: number }) => (
  <RIcon size={size}>
    <circle cx="7.5" cy="15.5" r="4.5" />
    <path d="m10.7 12.3 8.3-8.3" />
    <path d="m17 5 3 3" />
    <path d="m14 8 3 3" />
  </RIcon>
);
const IconLock = ({ size = 15 }: { size?: number }) => (
  <RIcon size={size}>
    <rect x="3" y="11" width="18" height="11" rx="2" />
    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
  </RIcon>
);
const IconChevron = ({ size = 14 }: { size?: number }) => (
  <RIcon size={size}>
    <path d="m9 18 6-6-6-6" />
  </RIcon>
);
const IconSearch = ({ size = 15 }: { size?: number }) => (
  <RIcon size={size}>
    <circle cx="11" cy="11" r="8" />
    <path d="m21 21-4.3-4.3" />
  </RIcon>
);

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const hasTz = /[+-]\d{2}:?\d{2}$|Z$/i.test(iso);
  return new Date(hasTz ? iso : iso + "Z").toLocaleString("th-TH", {
    timeZone: "Asia/Bangkok",
    dateStyle: "short",
    timeStyle: "short",
  });
}

export default function RecoveryTicketsPage() {
  const [items, setItems] = useState<RecoveryTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [verifying, setVerifying] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(
    null
  );
  const [link, setLink] = useState<{ id: string; url: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [query, setQuery] = useState("");
  const [level, setLevel] = useState<LevelFilter>("all");
  const [openId, setOpenId] = useState<string | null>(null);
  // per-ticket evidence form
  const [form, setForm] = useState<
    Record<string, { evidence_type: string; remark: string }>
  >({});

  const load = useCallback(() => {
    setLoading(true);
    adminListRecoveryTickets("pending")
      .then((d) => setItems(d.items))
      .catch((e) => setMsg({ kind: "err", text: e?.detail || "โหลดไม่สำเร็จ" }))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const f = (id: string) =>
    form[id] || { evidence_type: "student_card", remark: "" };

  async function approve(t: RecoveryTicket) {
    setBusy(t.id + "a");
    setMsg(null);
    try {
      const r = await adminApproveTicket(
        t.id,
        { evidence_type: f(t.id).evidence_type, remark: f(t.id).remark },
        setVerifying
      );
      if (r.relink_url) {
        setLink({ id: t.id, url: r.relink_url });
        setCopied(false);
        setMsg({ kind: "ok", text: "อนุมัติครบ — คัดลอกลิงก์ให้ผู้ใช้" });
      } else {
        setMsg({
          kind: "ok",
          text: `บันทึกการอนุมัติแล้ว (${r.approvals}/${r.required}) — รอ admin อีกคน (four-eyes)`,
        });
      }
      setOpenId(null);
      load();
    } catch (e) {
      const d = (e as { detail?: unknown })?.detail;
      setMsg({ kind: "err", text: typeof d === "string" ? d : "อนุมัติไม่สำเร็จ" });
    } finally {
      setBusy(null);
    }
  }

  async function reject(t: RecoveryTicket) {
    if (!confirm(`ปฏิเสธคำขอของ ${t.email}?`)) return;
    setBusy(t.id + "r");
    try {
      await adminRejectTicket(t.id, setVerifying);
      setMsg({ kind: "ok", text: "ปฏิเสธแล้ว" });
      setOpenId(null);
      load();
    } catch (e) {
      setMsg({
        kind: "err",
        text: (e as { detail?: string })?.detail || "ไม่สำเร็จ",
      });
    } finally {
      setBusy(null);
    }
  }

  const kpis = useMemo(() => {
    const high = items.filter((t) => t.recovery_level === "HIGH").length;
    const normal = items.length - high;
    const waiting = items.filter(
      (t) => t.recovery_level === "HIGH" && t.approvals < t.required
    ).length;
    return { pending: items.length, high, normal, waiting };
  }, [items]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter((t) => {
      if (level !== "all" && t.recovery_level !== level) return false;
      if (!q) return true;
      return (
        t.email.toLowerCase().includes(q) ||
        t.id.toLowerCase().includes(q) ||
        (t.reason || "").toLowerCase().includes(q) ||
        (t.credential_type || "").toLowerCase().includes(q)
      );
    });
  }, [items, query, level]);

  return (
    <div className="sc">
      {verifying && (
        <div className="cx-verify-overlay">
          <div>กำลังยืนยันด้วย Passkey — ทำตามที่อุปกรณ์แจ้ง</div>
        </div>
      )}

      <Topbar title="คำขอกู้บัญชี" />

      {/* ── Command bar ── */}
      <section className="cx-command">
        <div>
          <span>
            <span className="cx-dot warn">
              <i />
            </span>
            account recovery triage
          </span>
          <h1>คำขอกู้บัญชี</h1>
        </div>
        <div className="cx-live-actions">
          <button onClick={load}>
            <IconRefresh />
            รีเฟรชรายการ
          </button>
        </div>
      </section>

      <div className="cx-document">
        {msg && (
          <div className={msg.kind === "ok" ? "cx-inline-ok" : "cx-inline-error"}>
            {msg.text}
          </div>
        )}

        {/* ── KPI ── */}
        <section className="cx-kpis four" aria-label="สรุปคำขอกู้บัญชี">
          <article className="cx-kpi">
            <span className="mono">PENDING TICKETS</span>
            <strong>{loading ? "—" : kpis.pending}</strong>
            <small>รอตรวจสอบทั้งหมด</small>
          </article>
          <article className="cx-kpi danger">
            <span className="mono">HIGH RECOVERY RISK</span>
            <strong>{loading ? "—" : kpis.high}</strong>
            <small>ต้อง admin 2 คน (four-eyes)</small>
          </article>
          <article className="cx-kpi">
            <span className="mono">NORMAL</span>
            <strong>{loading ? "—" : kpis.normal}</strong>
            <small>อนุมัติโดย admin 1 คน</small>
          </article>
          <article className="cx-kpi info">
            <span className="mono">รอ 4-EYES</span>
            <strong>{loading ? "—" : kpis.waiting}</strong>
            <small>HIGH ที่ยังอนุมัติไม่ครบ</small>
          </article>
        </section>

        {/* ── ตาราง triage ── */}
        <section className="cx-panel">
          <header>
            <div>
              <span className="mono">account recovery triage</span>
              <h2>คำขอกู้บัญชีที่รอตรวจสอบ</h2>
            </div>
            <span className="cx-chip warn">
              <IconKey />
              STEP-UP REQUIRED
            </span>
          </header>

          <div className="cx-toolbar">
            <label>
              <IconSearch />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="อีเมล, Ticket ID หรือเหตุผล"
                aria-label="ค้นหาคำขอ"
              />
            </label>
            <div className="cx-filter-chips">
              {(
                [
                  { key: "all", label: "ทุกระดับ" },
                  { key: "HIGH", label: "HIGH" },
                  { key: "NORMAL", label: "NORMAL" },
                ] as Array<{ key: LevelFilter; label: string }>
              ).map((c) => (
                <button
                  key={c.key}
                  className={level === c.key ? "on" : ""}
                  onClick={() => setLevel(c.key)}
                >
                  {c.label}
                </button>
              ))}
            </div>
          </div>

          {loading ? (
            <div className="cx-empty">
              <strong>กำลังโหลด</strong>
            </div>
          ) : filtered.length === 0 ? (
            <div className="cx-empty">
              <IconKey size={26} />
              <strong>
                {items.length === 0 ? "ไม่มีคำขอรออนุมัติ" : "ไม่พบคำขอตามตัวกรอง"}
              </strong>
              {items.length === 0 && <span>ระบบทำงานปกติ</span>}
            </div>
          ) : (
            <div className="cx-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th style={{ width: 110 }}>Ticket</th>
                    <th>User email</th>
                    <th>Reason</th>
                    <th style={{ width: 96 }}>Level</th>
                    <th style={{ width: 150 }}>Requested</th>
                    <th style={{ width: 96 }}>Signals</th>
                    <th style={{ width: 120, textAlign: "right" }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((t) => {
                    const open = openId === t.id;
                    return (
                      <FragmentRow key={t.id}>
                        <tr>
                          <td className="mono">{t.id.slice(0, 8)}</td>
                          <td>{t.email}</td>
                          <td>
                            {t.reason || "ไม่ระบุเหตุผล"}
                            {t.credential_type && (
                              <div className="cx-notif-sub">
                                แจ้งหาย: {t.credential_type}
                              </div>
                            )}
                          </td>
                          <td>
                            <span
                              className={`cx-level ${
                                t.recovery_level === "HIGH" ? "high" : "normal"
                              }`}
                            >
                              {t.recovery_level}
                            </span>
                          </td>
                          <td className="mono" style={{ fontSize: 10 }}>
                            {fmtTime(t.created_at)}
                          </td>
                          <td className="mono">
                            {t.approvals}/{t.required}
                          </td>
                          <td>
                            <div
                              style={{
                                display: "flex",
                                justifyContent: "flex-end",
                              }}
                            >
                              <button
                                className="cx-panel-action"
                                onClick={() => setOpenId(open ? null : t.id)}
                              >
                                {open ? "ปิด" : "ตรวจสอบ"}
                                <IconChevron />
                              </button>
                            </div>
                          </td>
                        </tr>
                        {open && (
                          <tr className="cx-recovery-expand">
                            <td colSpan={7}>
                              <div className="cx-evidence-form">
                                <label>
                                  หลักฐานที่ตรวจ
                                  <select
                                    value={f(t.id).evidence_type}
                                    onChange={(e) =>
                                      setForm((s) => ({
                                        ...s,
                                        [t.id]: {
                                          ...f(t.id),
                                          evidence_type: e.target.value,
                                        },
                                      }))
                                    }
                                  >
                                    {EVIDENCE.map((ev) => (
                                      <option key={ev.v} value={ev.v}>
                                        {ev.label}
                                      </option>
                                    ))}
                                  </select>
                                </label>
                                <input
                                  value={f(t.id).remark}
                                  onChange={(e) =>
                                    setForm((s) => ({
                                      ...s,
                                      [t.id]: {
                                        ...f(t.id),
                                        remark: e.target.value,
                                      },
                                    }))
                                  }
                                  placeholder="หมายเหตุ (เช่น เลขบัตร, ผู้ตรวจ)"
                                  aria-label="หมายเหตุการตรวจ"
                                />
                                <button
                                  className="cx-approve"
                                  onClick={() => approve(t)}
                                  disabled={busy === t.id + "a"}
                                >
                                  {busy === t.id + "a"
                                    ? "กำลังบันทึก"
                                    : t.required > t.approvals + 1
                                      ? "อนุมัติ (1/2)"
                                      : "อนุมัติ → ออกลิงก์"}
                                </button>
                                <button
                                  className="cx-reject"
                                  onClick={() => reject(t)}
                                  disabled={busy === t.id + "r"}
                                >
                                  ปฏิเสธ
                                </button>
                              </div>
                            </td>
                          </tr>
                        )}
                      </FragmentRow>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* ── flow + one-time secret ── */}
        <section className="cx-recovery-grid">
          <article className="cx-panel">
            <header>
              <div>
                <span className="mono">approval flow</span>
                <h2>ขั้นตอนอนุมัติที่ปลอดภัย</h2>
              </div>
            </header>
            <div className="cx-recovery-flow">
              <span>
                <b className="mono">01</b>
                <small>ตรวจหลักฐานตัวตน</small>
              </span>
              <IconChevron />
              <span>
                <b className="mono">02</b>
                <small>ยืนยัน Step-up</small>
              </span>
              <IconChevron />
              <span>
                <b className="mono">03</b>
                <small>สร้าง Recovery link</small>
              </span>
            </div>
          </article>

          <article className="cx-panel">
            <header>
              <div>
                <span className="mono">one-time secret</span>
                <h2>Recovery link</h2>
              </div>
              <IconLock />
            </header>
            {link ? (
              <div className="cx-recovery-secret">
                <small>ใช้ครั้งเดียว · 30 นาที — ส่งให้ผู้ใช้เปิดเอง</small>
                <code>{link.url}</code>
                <button
                  onClick={() => {
                    navigator.clipboard?.writeText(link.url);
                    setCopied(true);
                  }}
                >
                  {copied ? "คัดลอกแล้ว" : "คัดลอกลิงก์"}
                </button>
              </div>
            ) : (
              <div className="cx-recovery-secret empty">
                <code>ลิงก์จะแสดงครั้งเดียวหลังอนุมัติครบ</code>
                <button disabled>คัดลอกลิงก์</button>
              </div>
            )}
          </article>
        </section>
      </div>
    </div>
  );
}

// table แถวหลัก + แถวขยาย ต้องเป็นพี่น้องใน <tbody> — ครอบด้วย Fragment
function FragmentRow({ children }: { children: ReactNode }) {
  return <>{children}</>;
}