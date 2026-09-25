"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { clientFetch } from "@/lib/api";

type ChangeRequest = {
  id: string;
  subsystem_name: string;
  request_type: string;
  created_at: string | null;
};

type ChangeRequestResponse = {
  items: ChangeRequest[];
  total: number;
};

type PendingSubsystem = {
  id: string;
  name: string;
  client_id: string;
  created_at?: string | null;
};

type QueueItem = {
  id: string;
  title: string;
  subtitle: string;
  code: string;
  createdAt: string | null;
  href: string;
  tone: "subsystem" | "change" | "owner";
};

const REQUEST_LABELS: Record<string, string> = {
  rotate_secret: "หมุน Client Secret",
  edit_scope: "แก้ไข Scope",
  edit_allowed_roles: "แก้ไข Allowed Roles",
  edit_redirect_uris: "แก้ไข Redirect URI",
  change_whitelist_role: "เปลี่ยน Role",
  bulk_change_whitelist_roles: "เปลี่ยน Role แบบกลุ่ม",
  owner_transfer: "โอนสิทธิ์เจ้าของ",
};

function requestLabel(value: string) {
  return REQUEST_LABELS[value] || value.replaceAll("_", " ");
}

function parseUTC(value: string) {
  return new Date(/[+-]\d{2}:?\d{2}$|Z$/i.test(value) ? value : `${value}Z`);
}

function timeAgo(value: string | null) {
  if (!value) return "—";
  const seconds = Math.max(0, Math.floor((Date.now() - parseUTC(value).getTime()) / 1000));
  if (seconds < 60) return "now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} hr`;
  return `${Math.floor(seconds / 86400)} d`;
}

function QueueIcon({ tone }: { tone: QueueItem["tone"] }) {
  if (tone === "owner") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="8" r="4" />
        <path d="M5 21v-2a7 7 0 0 1 14 0v2" />
      </svg>
    );
  }
  if (tone === "change") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 3 14 5.2l3-.2.8 2.9 2.5 1.7-1.3 2.7 1.3 2.7-2.5 1.7-.8 2.9-3-.2L12 22l-2-2.6-3 .2-.8-2.9L3.7 15 5 12.3 3.7 9.6 6.2 8 7 5l3 .2z" />
        <circle cx="12" cy="12.3" r="3" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="6" cy="6" r="2" />
      <circle cx="18" cy="6" r="2" />
      <circle cx="6" cy="18" r="2" />
      <circle cx="18" cy="18" r="2" />
      <path d="M8 6h8M6 8v8M18 8v8M8 18h8" />
    </svg>
  );
}

export function PendingQueueCard() {
  const [items, setItems] = useState<QueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;

    Promise.allSettled([
      clientFetch<PendingSubsystem[]>("/admin/subsystems?status=pending"),
      clientFetch<ChangeRequestResponse>("/admin/change-requests?status=pending&limit=100"),
    ]).then(([subsystemsResult, changesResult]) => {
      if (!active) return;

      const subsystems = subsystemsResult.status === "fulfilled" ? subsystemsResult.value : [];
      const changes = changesResult.status === "fulfilled" ? changesResult.value : { items: [], total: 0 };
      const queue: QueueItem[] = [
        ...subsystems.map((item) => ({
          id: `subsystem-${item.id}`,
          title: "อนุมัติระบบย่อย",
          subtitle: item.name,
          code: item.client_id || item.id,
          createdAt: item.created_at || null,
          href: "/subsystems/pending",
          tone: "subsystem" as const,
        })),
        ...changes.items.map((item) => ({
          id: `change-${item.id}`,
          title: requestLabel(item.request_type),
          subtitle: item.subsystem_name,
          code: `req_${item.id.slice(0, 7)}`,
          createdAt: item.created_at,
          href: "/pending-requests",
          tone: item.request_type === "owner_transfer" ? ("owner" as const) : ("change" as const),
        })),
      ].sort((a, b) => {
        const at = a.createdAt ? parseUTC(a.createdAt).getTime() : 0;
        const bt = b.createdAt ? parseUTC(b.createdAt).getTime() : 0;
        return bt - at;
      });

      setItems(queue.slice(0, 3));
      setTotal(subsystems.length + changes.total);
      setFailed(subsystemsResult.status === "rejected" && changesResult.status === "rejected");
      setLoading(false);
    });

    return () => {
      active = false;
    };
  }, []);

  return (
    <section className="card queue-card">
      <div className="card-head">
        <div>
          <span className="overline">pending queue</span>
          <h2>งานที่รอการตัดสินใจ</h2>
        </div>
        <strong className="queue-count mono">{String(total).padStart(2, "0")}</strong>
      </div>

      <div className="queue-list">
        {loading ? (
          <div className="queue-empty">กำลังโหลด…</div>
        ) : failed ? (
          <div className="queue-empty">โหลดคิวงานไม่สำเร็จ</div>
        ) : items.length === 0 ? (
          <div className="queue-empty">ไม่มีงานที่รอการตัดสินใจ</div>
        ) : (
          items.map((item) => (
            <Link key={item.id} href={item.href} className="queue-item">
              <span className={`queue-icon ${item.tone}`}>
                <QueueIcon tone={item.tone} />
              </span>
              <span className="min-w-0">
                <strong>{item.title}</strong>
                <span className="truncate">{item.subtitle}</span>
                <code className="mono truncate">{item.code}</code>
              </span>
              <time className="mono">{timeAgo(item.createdAt)}</time>
              <span className="queue-chevron" aria-hidden="true">›</span>
            </Link>
          ))
        )}
      </div>

      <Link href="/notifications" className="queue-all">
        ดูคิวทั้งหมด <span aria-hidden="true">→</span>
      </Link>
    </section>
  );
}
