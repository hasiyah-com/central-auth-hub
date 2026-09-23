"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";
import { parseUserAgent } from "@/lib/ua";
// design system เดียวกับหน้าคอนโซล — .sc = ชุด cx-*
import "../../signal-room.css";
import "../../signal-console.css";

type AuditLog = {
  id: string;
  actor_id: string | null;
  actor_email: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  ip: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string | null;
  [k: string]: unknown;
};

type AuditResponse = {
  items: AuditLog[];
  total: number;
  skip: number;
  limit: number;
};

type Tone = "signal" | "warn" | "danger" | "default";

function actionTone(action: string): Tone {
  if (action.includes("approved") || action.includes("success")) return "signal";
  if (
    action.includes("rejected") ||
    action.includes("failed") ||
    action.includes("blocked")
  )
    return "danger";
  if (action.includes("revoked") || action.includes("suspended")) return "warn";
  return "default";
}

function resultLabel(tone: Tone): string {
  return tone === "danger"
    ? "ล้มเหลว"
    : tone === "warn"
    ? "เพิกถอน"
    : tone === "signal"
    ? "สำเร็จ"
    : "บันทึก";
}

function toDate(iso: string | null): Date | null {
  if (!iso) return null;
  try {
    const hasTz = /[+-]\d{2}:?\d{2}$|Z$/i.test(iso);
    const d = new Date(hasTz ? iso : iso + "Z");
    return isNaN(d.getTime()) ? null : d;
  } catch {
    return null;
  }
}

function fmtDate(iso: string | null): string {
  const d = toDate(iso);
  if (!d) return "—";
  return d.toLocaleDateString("th-TH", {
    timeZone: "Asia/Bangkok",
    day: "2-digit",
    month: "short",
    year: "2-digit",
  });
}

function fmtClock(iso: string | null): string {
  const d = toDate(iso);
  if (!d) return "—";
  return d.toLocaleTimeString("th-TH", {
    timeZone: "Asia/Bangkok",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

const PAGE_SIZE = 50;

const ACTION_OPTIONS = [
  { v: "", label: "ทุก Action" },
  { v: "hub_login_success", label: "เข้าสู่ระบบสำเร็จ" },
  { v: "hub_login_failed", label: "เข้าสู่ระบบล้มเหลว" },
  { v: "subsystem_approved", label: "อนุมัติระบบย่อย" },
  { v: "subsystem_rejected", label: "ปฏิเสธระบบย่อย" },
  { v: "user_updated", label: "แก้ไขผู้ใช้" },
];

function AuditPageInner() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const targetId = searchParams.get("target_id");
  const targetEmail = searchParams.get("target_email");
  const actorId = searchParams.get("actor_id");
  const actorEmail = searchParams.get("actor_email");
  const scopeId = targetId || actorId;
  const scopeEmail = targetEmail || actorEmail;
  const scopeLabel = targetId ? "เป็นเป้าหมาย" : "กระทำเอง";

  const [data, setData] = useState<AuditResponse | null>(null);
  const [action, setAction] = useState<string>("");
  const [targetType, setTargetType] = useState<string>(targetId ? "user" : "");
  const [q, setQ] = useState("");
  const [skip, setSkip] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  function load() {
    setLoading(true);
    setError(null);
    const qs = new URLSearchParams();
    if (action) qs.set("action", action);
    if (targetType) qs.set("target_type", targetType);
    if (targetId) qs.set("target_id", targetId);
    if (actorId) qs.set("actor_id", actorId);
    qs.set("skip", String(skip));
    qs.set("limit", String(PAGE_SIZE));
    clientFetch<AuditResponse>(`/admin/audit?${qs.toString()}`)
      .then(setData)
      .catch((e) => setError(e.detail || "โหลด audit log ไม่สำเร็จ"))
      .finally(() => setLoading(false));
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [action, targetType, targetId, actorId, skip]);

  // กลับหน้าแรกเมื่อเปลี่ยนตัวกรอง — กันค้างอยู่หน้า 3 แล้วเจอจอว่าง
  useEffect(() => {
    setSkip(0);
    setSelected(null);
  }, [action, targetType, targetId, actorId]);

  const items = data?.items ?? [];

  // ค้นหาในหน้าที่โหลดมาแล้ว (API ยังไม่มีพารามิเตอร์ค้นหา)
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return items;
    return items.filter((r) =>
      [r.actor_email, r.action, r.target_type, r.target_id, r.ip]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(needle))
    );
  }, [items, q]);

  const current = shown.find((r) => r.id === selected) ?? shown[0] ?? null;

  const total = data?.total ?? 0;
  const page = Math.floor(skip / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // นับจาก "หน้าที่โหลดมา" เท่านั้น — ไม่ใช่ทั้งระบบ label จึงบอกให้ชัด
  const onPage = useMemo(() => {
    const t = { danger: 0, warn: 0 };
    items.forEach((r) => {
      const tone = actionTone(r.action);
      if (tone === "danger") t.danger += 1;
      if (tone === "warn") t.warn += 1;
    });
    return t;
  }, [items]);

  return (
    <div className="sc">
      <Topbar title="Audit Log" />

      <section className="cx-command">
        <div>
          <span>
            <span className="cx-dot">
              <i />
            </span>
            immutable event stream
          </span>
          <h1>Audit Log</h1>
        </div>
        <div className="cx-audit-actions">
          <span className="cx-chip mono">
            {data === null ? "กำลังโหลด…" : `${total.toLocaleString("th-TH")} events`}
          </span>
        </div>
      </section>

      <main className="cx-document">
        {/* ── แถบสรุป — แสดงเฉพาะค่าที่คำนวณจากข้อมูลจริงได้ ── */}
        <section className="cx-audit-status">
          <div className="cx-audit-status-copy">
            <div>
              <small className="mono">AUDIT INTEGRITY</small>
              <h2>บันทึกทุกการเปลี่ยนแปลง ตรวจสอบย้อนหลังได้</h2>
            </div>
          </div>
          <div className="cx-audit-summary">
            <span>
              <small>เหตุการณ์ทั้งหมด</small>
              <b className="mono">
                {data === null ? "—" : total.toLocaleString("th-TH")}
              </b>
            </span>
            <span>
              <small>ล้มเหลว / ปฏิเสธ (หน้านี้)</small>
              <b className="mono danger">{data === null ? "—" : onPage.danger}</b>
            </span>
            <span>
              <small>เพิกถอน / ระงับ (หน้านี้)</small>
              <b className="mono">{data === null ? "—" : onPage.warn}</b>
            </span>
            <span>
              <small>แสดงอยู่</small>
              <b className="mono signal">
                {data === null ? "—" : `${page}/${totalPages}`}
              </b>
            </span>
          </div>
        </section>

        {scopeId && (
          <div className="cx-msg ok">
            กำลังดู log ที่ <b>{scopeEmail || scopeId}</b> {scopeLabel} เท่านั้น
            <button
              onClick={() => router.push("/audit")}
              className="cx-chip"
              style={{ marginLeft: "auto" }}
            >
              ดูทั้งหมด
            </button>
          </div>
        )}

        {error && <div className="cx-msg err">{error}</div>}

        <section className="cx-audit-workspace">
          {/* ── รายการเหตุการณ์ ── */}
          <article className="cx-panel cx-audit-log">
            <header>
              <div>
                <span className="mono">IMMUTABLE EVENT STREAM</span>
                <h2>รายการ Audit Log</h2>
              </div>
              <span className="cx-audit-count mono">
                {loading ? "กำลังโหลด…" : `${shown.length} รายการในหน้านี้`}
              </span>
            </header>

            <div className="cx-audit-toolbar">
              <label>
                <input
                  aria-label="ค้นหา Audit Log"
                  placeholder="ค้นหาอีเมล, Action, Target หรือ IP (ในหน้านี้)"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                />
              </label>
              <select
                value={action}
                onChange={(e) => setAction(e.target.value)}
                aria-label="กรองตาม action"
              >
                {ACTION_OPTIONS.map((o) => (
                  <option key={o.v} value={o.v}>
                    {o.label}
                  </option>
                ))}
              </select>
              <select
                value={targetType}
                onChange={(e) => setTargetType(e.target.value)}
                aria-label="กรองตามประเภทเป้าหมาย"
              >
                <option value="">ทุกเป้าหมาย</option>
                <option value="user">user</option>
                <option value="subsystem">subsystem</option>
                <option value="session">session</option>
              </select>
            </div>

            <div className="cx-audit-table-head mono">
              <span>TIME · ASIA/BANGKOK</span>
              <span>ACTOR</span>
              <span>ACTION</span>
              <span>TARGET</span>
              <span>RESULT</span>
              <span />
            </div>

            {shown.length === 0 ? (
              <div className="cx-empty">
                <strong>
                  {loading ? "กำลังโหลด…" : "ไม่พบเหตุการณ์ตามเงื่อนไขนี้"}
                </strong>
              </div>
            ) : (
              <div className="cx-audit-rows">
                {shown.map((r) => {
                  const tone = actionTone(r.action);
                  return (
                    <button
                      key={r.id}
                      className={current?.id === r.id ? "selected" : ""}
                      onClick={() => setSelected(r.id)}
                    >
                      <time>
                        <b>{fmtClock(r.created_at)}</b>
                        <small>{fmtDate(r.created_at)}</small>
                      </time>
                      <span className="actor">
                        <b>{r.actor_email || "system"}</b>
                        <small className="mono">
                          {r.actor_email ? "USER" : "SYSTEM SERVICE"}
                        </small>
                      </span>
                      <span>
                        <i className={tone}>{r.action}</i>
                        <small className="mono">{r.id.slice(0, 8)}</small>
                      </span>
                      <span className="target">
                        <b>{r.target_type || "—"}</b>
                        <small className="mono">{r.ip || "—"}</small>
                      </span>
                      <span className={`result ${tone}`}>
                        <span className={`cx-dot ${tone === "default" ? "" : tone}`}>
                          <i />
                        </span>
                        {resultLabel(tone)}
                      </span>
                      <span aria-hidden="true">›</span>
                    </button>
                  );
                })}
              </div>
            )}

            <div className="cx-audit-pagination">
              <span>
                {total === 0
                  ? "ไม่มีรายการ"
                  : `แสดง ${skip + 1}–${Math.min(skip + PAGE_SIZE, total)} จาก ${total.toLocaleString("th-TH")} รายการ`}
              </span>
              <div>
                <button
                  onClick={() => setSkip(Math.max(0, skip - PAGE_SIZE))}
                  disabled={skip === 0 || loading}
                >
                  ก่อนหน้า
                </button>
                <b className="mono">
                  {String(page).padStart(2, "0")} / {String(totalPages).padStart(2, "0")}
                </b>
                <button
                  onClick={() => setSkip(skip + PAGE_SIZE)}
                  disabled={skip + PAGE_SIZE >= total || loading}
                >
                  ถัดไป
                </button>
              </div>
            </div>
          </article>

          {/* ── รายละเอียดเหตุการณ์ที่เลือก ── */}
          <aside className="cx-panel cx-audit-detail">
            <header>
              <div>
                <span className="mono">EVENT INSPECTOR</span>
                <h2>รายละเอียดเหตุการณ์</h2>
              </div>
              {current && (
                <span className={`cx-chip ${actionTone(current.action)}`}>
                  {resultLabel(actionTone(current.action))}
                </span>
              )}
            </header>

            {!current ? (
              <div className="cx-empty sm">
                <strong>เลือกเหตุการณ์เพื่อดูรายละเอียด</strong>
              </div>
            ) : (
              <>
                <div className="cx-audit-detail-id">
                  <small className="mono">ACTION</small>
                  <b className="mono">{current.action}</b>
                  <span className="mono">{current.id}</span>
                </div>

                <dl>
                  <div>
                    <dt>เวลา</dt>
                    <dd>
                      {fmtDate(current.created_at)} · {fmtClock(current.created_at)}
                    </dd>
                  </div>
                  <div>
                    <dt>ผู้ดำเนินการ</dt>
                    <dd>
                      {current.actor_email || "system"}
                      <small className="mono">
                        {current.actor_id || "ไม่มี actor_id"}
                      </small>
                    </dd>
                  </div>
                  <div>
                    <dt>เป้าหมาย</dt>
                    <dd>
                      {current.target_type || "—"}
                      {current.target_id && (
                        <small className="mono">{current.target_id}</small>
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>Source IP</dt>
                    <dd className="mono">{current.ip || "—"}</dd>
                  </div>
                  <div>
                    <dt>อุปกรณ์</dt>
                    <dd>
                      {parseUserAgent(
                        (current.metadata as { user_agent?: string } | null)
                          ?.user_agent
                      )?.label || "—"}
                    </dd>
                  </div>
                </dl>

                <div className="cx-audit-json">
                  <span className="mono">METADATA JSON</span>
                  <code>
                    {current.metadata && Object.keys(current.metadata).length > 0
                      ? JSON.stringify(current.metadata, null, 2)
                      : "—"}
                  </code>
                </div>
              </>
            )}
          </aside>
        </section>
      </main>
    </div>
  );
}

export default function AuditPage() {
  return (
    <Suspense fallback={null}>
      <AuditPageInner />
    </Suspense>
  );
}
