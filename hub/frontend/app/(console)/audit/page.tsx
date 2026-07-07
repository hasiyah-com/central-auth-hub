"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Topbar } from "@/components/Topbar";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge } from "@/components/Badge";
import { clientFetch } from "@/lib/api";
import { parseUserAgent } from "@/lib/ua";

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

// Tone hints for common action prefixes — visual scanning aid only,
// fall through to "default" for anything not listed.
function actionTone(action: string): "brand" | "good" | "warn" | "danger" | "default" {
  if (action.includes("approved") || action.includes("success")) return "good";
  if (action.includes("rejected") || action.includes("failed") || action.includes("blocked"))
    return "danger";
  if (action.includes("login") || action.includes("token")) return "brand";
  if (action.includes("revoked") || action.includes("suspended")) return "warn";
  return "default";
}

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  // Server stores UTC; display in Asia/Bangkok per project convention.
  // FastAPI ส่ง naive datetime (เช่น "2026-05-29T11:14:26" ไม่มี Z) —
  // new Date() จะตีความเป็น local time → เพี้ยน 7 ชม.
  // บังคับ append "Z" ถ้ายังไม่มี timezone marker
  try {
    const hasTz = /[+-]\d{2}:?\d{2}$|Z$/i.test(iso);
    const d = new Date(hasTz ? iso : iso + "Z");
    return d.toLocaleString("th-TH", {
      timeZone: "Asia/Bangkok",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return iso;
  }
}

const PAGE_SIZE = 50;

// แสดงรายละเอียด audit แบบอ่านง่าย: surface field สำคัญ (ต้นทาง/เหตุผล/เป้าหมาย)
// ก่อน raw JSON — ตอบ "เข้าทางไหน ใช้อะไร ทำอะไร" ได้ทันทีโดยไม่ต้องอ่าน JSON
function DetailCell({ row }: { row: AuditLog }) {
  const meta = row.metadata as Record<string, unknown> | null;
  if (!meta || Object.keys(meta).length === 0) {
    return <span className="text-ink-400 text-xs">—</span>;
  }
  const ua = parseUserAgent(meta.user_agent as string | undefined);
  // key fields ที่อยากเชิดขึ้นมา (ถ้ามี)
  const highlights: [string, string][] = [];
  if (meta.email) highlights.push(["อีเมล", String(meta.email)]);
  if (meta.reason) highlights.push(["เหตุผล", String(meta.reason)]);
  if (meta.role) highlights.push(["role", String(meta.role)]);
  if (meta.provider) highlights.push(["provider", String(meta.provider)]);
  if (ua) highlights.push(["อุปกรณ์", ua.label]);

  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-brand-600 hover:text-brand-700">
        ดูรายละเอียด
      </summary>
      <div className="mt-1.5 space-y-1.5 max-w-md">
        {highlights.length > 0 && (
          <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 p-2 bg-brand-50 rounded border border-brand-100">
            {highlights.map(([k, v]) => (
              <div key={k} className="contents">
                <span className="text-ink-500">{k}</span>
                <span className="font-mono text-ink-800 break-all">{v}</span>
              </div>
            ))}
          </div>
        )}
        <details className="text-[10px]">
          <summary className="cursor-pointer text-ink-400 hover:text-ink-600">
            raw JSON
          </summary>
          <pre className="mt-1 p-2 bg-ink-50 rounded overflow-x-auto">
            {JSON.stringify(meta, null, 2)}
          </pre>
        </details>
      </div>
    </details>
  );
}

function AuditPageInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  // มาจาก User 360 view ("ดู Audit Log") — ล็อก scope ไว้ที่ user คนเดียว
  // target_id = สิ่งที่ถูกกระทำต่อ user นี้ (admin แก้/revoke ให้)
  // actor_id  = สิ่งที่ user นี้ทำเอง (login, กระทำต่อคนอื่น)
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
  const [skip, setSkip] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  // Reset to page 1 whenever a filter changes — avoid stuck-on-page-3 surprise.
  useEffect(() => {
    setSkip(0);
  }, [action, targetType, targetId, actorId]);

  const columns: Column<AuditLog>[] = [
    {
      key: "created_at",
      header: "เวลา",
      render: (r) => (
        <span className="font-mono text-xs whitespace-nowrap">
          {formatTime(r.created_at)}
        </span>
      ),
    },
    {
      key: "actor_email",
      header: "ผู้กระทำ",
      render: (r) =>
        r.actor_email ? (
          <span className="font-mono text-xs">{r.actor_email}</span>
        ) : (
          <span className="text-ink-400 italic text-xs">system</span>
        ),
    },
    {
      key: "action",
      header: "การกระทำ",
      render: (r) => <Badge tone={actionTone(r.action)}>{r.action}</Badge>,
    },
    {
      key: "target_type",
      header: "Target",
      render: (r) => (
        <div className="text-xs">
          <div>{r.target_type || "—"}</div>
          {r.target_id && (
            <div className="font-mono text-ink-500 text-[10px] truncate max-w-[180px]">
              {r.target_id}
            </div>
          )}
        </div>
      ),
    },
    {
      key: "ip",
      header: "ต้นทาง (IP · อุปกรณ์)",
      render: (r) => {
        const ua = parseUserAgent(
          (r.metadata as { user_agent?: string } | null)?.user_agent
        );
        return (
          <div className="text-xs">
            <div className="font-mono">{r.ip || "—"}</div>
            {ua && (
              <div className="text-ink-500 text-[10px] mt-0.5" title={ua.raw}>
                🖥️ {ua.label}
              </div>
            )}
          </div>
        );
      },
    },
    {
      key: "metadata",
      header: "รายละเอียด",
      render: (r) => <DetailCell row={r} />,
    },
  ];

  const total = data?.total ?? 0;
  const page = Math.floor(skip / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      <Topbar title="Audit Log" />
      <main className="p-8 max-w-7xl mx-auto w-full">
        {scopeId && (
          <div className="mb-5 flex items-center gap-2 px-4 py-2.5 rounded-lg bg-brand-50 border border-brand-200 text-sm text-brand-800">
            <span>
              กำลังดู log ที่ <strong>{scopeEmail || scopeId}</strong> {scopeLabel} เท่านั้น
            </span>
            <button
              onClick={() => router.push("/audit")}
              className="ml-auto text-xs px-2.5 py-1 rounded-md border border-brand-300 hover:bg-brand-100"
            >
              ดูทั้งหมด ✕
            </button>
          </div>
        )}
        <div className="mb-5 flex flex-wrap items-center gap-3">
          <input
            type="text"
            placeholder="filter action (เช่น subsystem_approved)…"
            value={action}
            onChange={(e) => setAction(e.target.value)}
            className="px-3 py-2 rounded-lg border border-ink-200 bg-white text-sm focus:outline-none focus:border-brand-500 w-72 font-mono"
          />
          <select
            value={targetType}
            onChange={(e) => setTargetType(e.target.value)}
            className="px-3 py-2 rounded-lg border border-ink-200 bg-white text-sm focus:outline-none focus:border-brand-500"
          >
            <option value="">ทุก target</option>
            <option value="user">user</option>
            <option value="subsystem">subsystem</option>
            <option value="access_list">access_list</option>
            <option value="login_session">login_session</option>
          </select>
          <div className="ml-auto text-xs text-ink-500">
            {loading
              ? "กำลังโหลด…"
              : `${data?.items.length ?? 0} / ${total} รายการ — หน้า ${page}/${totalPages}`}
          </div>
        </div>

        {error && (
          <div className="mb-5 p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm">
            {error}
          </div>
        )}

        <DataTable
          columns={columns}
          rows={data?.items ?? []}
          emptyMessage="ไม่พบ audit log ที่ตรงเงื่อนไข"
        />

        {/* Pagination — only show when there's more than one page */}
        {totalPages > 1 && (
          <div className="mt-5 flex items-center justify-between text-sm">
            <button
              type="button"
              onClick={() => setSkip(Math.max(0, skip - PAGE_SIZE))}
              disabled={skip === 0 || loading}
              className="px-4 py-2 rounded-lg border border-ink-200 bg-white hover:bg-ink-50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              ← ก่อนหน้า
            </button>
            <div className="text-ink-500">
              หน้า {page} / {totalPages}
            </div>
            <button
              type="button"
              onClick={() => setSkip(skip + PAGE_SIZE)}
              disabled={skip + PAGE_SIZE >= total || loading}
              className="px-4 py-2 rounded-lg border border-ink-200 bg-white hover:bg-ink-50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              ถัดไป →
            </button>
          </div>
        )}
      </main>
    </>
  );
}

export default function AuditPage() {
  return (
    <Suspense fallback={null}>
      <AuditPageInner />
    </Suspense>
  );
}
