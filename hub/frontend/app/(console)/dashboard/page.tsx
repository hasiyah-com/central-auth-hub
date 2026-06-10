"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { StatsCard } from "@/components/StatsCard";
import { clientFetch } from "@/lib/api";

type Overview = {
  users: { total: number; active: number };
  subsystems: { total: number; active: number; pending: number };
  logins: { total: number; blocked: number };
};

type UserCount = Record<string, number>;

type NotifCount = {
  total: number;
  unread?: number; // admin คนปัจจุบันยังไม่อ่าน (banner ใช้ตัวนี้)
  by_category: {
    approval_requests: number;
    ml_anomaly: number;
    api_alerts: number;
    subsystem_health: number;
  };
};

const CATEGORY_LABELS: Record<string, { label: string; icon: string }> = {
  approval_requests: { label: "คำขอ Approve", icon: "📋" },
  ml_anomaly: { label: "ML Anomaly", icon: "🧠" },
  api_alerts: { label: "API Alerts", icon: "🛡️" },
  subsystem_health: { label: "Subsystem ล่ม", icon: "🟢" },
};

type HealthCheckResult = {
  ok: boolean;
  emitted?: boolean;
  slot?: string;
  date?: string;
  subsystems?: number;
  includes_hub_self_check?: boolean;
  includes_api_alerts_summary?: boolean;
};

export default function DashboardPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [counts, setCounts] = useState<UserCount | null>(null);
  const [notif, setNotif] = useState<NotifCount | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hcBusy, setHcBusy] = useState(false);
  const [hcResult, setHcResult] = useState<HealthCheckResult | null>(null);
  const [hcError, setHcError] = useState<string | null>(null);

  const runHealthCheckNow = async () => {
    setHcBusy(true);
    setHcError(null);
    setHcResult(null);
    try {
      const res = await clientFetch<HealthCheckResult>(
        "/admin/subsystems/health/emit-summary-now",
        { method: "POST" }
      );
      setHcResult(res);
      // refresh notification count ทันที (summary ใหม่จะโผล่ใน /notifications)
      clientFetch<NotifCount>("/admin/notifications/count")
        .then(setNotif)
        .catch(() => {});
    } catch (e) {
      const err = e as { detail?: string };
      setHcError(err.detail || "ตรวจสอบไม่สำเร็จ");
    } finally {
      setHcBusy(false);
    }
  };

  useEffect(() => {
    Promise.all([
      clientFetch<Overview>("/admin/overview"),
      clientFetch<UserCount>("/admin/users/count"),
      clientFetch<NotifCount>("/admin/notifications/count").catch(() => null),
    ])
      .then(([ov, ct, nc]) => {
        setData(ov);
        setCounts(ct);
        if (nc) setNotif(nc);
      })
      .catch((e) => setError(e.detail || "โหลดข้อมูลไม่สำเร็จ"));

    const t = setInterval(() => {
      clientFetch<NotifCount>("/admin/notifications/count")
        .then(setNotif)
        .catch(() => {});
    }, 30_000);
    return () => clearInterval(t);
  }, []);

  return (
    <>
      <Topbar title="ภาพรวมระบบ" />
      <main className="p-8 max-w-7xl mx-auto w-full">
        {error && (
          <div className="mb-6 p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm">
            {error}
          </div>
        )}

        {!data && !error && (
          <div className="text-ink-400 text-sm">กำลังโหลด…</div>
        )}

        {/* Action bar — ปุ่ม run health check + manual report */}
        <div className="mb-6 flex flex-wrap items-center gap-3">
          <button
            onClick={runHealthCheckNow}
            disabled={hcBusy}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 disabled:bg-ink-300 disabled:cursor-not-allowed text-white text-sm font-bold shadow-sm hover:shadow transition"
          >
            {hcBusy ? (
              <>
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  className="w-4 h-4 animate-spin"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
                  />
                </svg>
                <span>กำลังตรวจ…</span>
              </>
            ) : (
              <>
                <span className="text-lg">🩺</span>
                <span>เช็คสุขภาพระบบตอนนี้</span>
              </>
            )}
          </button>

          {hcResult && hcResult.ok && (
            <div className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs">
              <span className="text-base">✓</span>
              <span>
                ตรวจเสร็จ — Hub + {hcResult.subsystems} subsystem
              </span>
              <Link
                href="/notifications"
                className="ml-1 font-bold underline hover:no-underline"
              >
                ดูรายงาน →
              </Link>
            </div>
          )}

          {hcError && (
            <div className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-rose-50 border border-rose-200 text-rose-800 text-xs">
              <span className="text-base">✗</span>
              <span>{hcError}</span>
            </div>
          )}
        </div>

        {/* Notifications Banner — แสดงเฉพาะถ้ามี unread ที่ admin ยังไม่ดู */}
        {notif && (notif.unread ?? 0) > 0 && (
          <Link
            href="/notifications"
            className="block mb-6 bg-gradient-to-r from-amber-50 to-orange-50 border-2 border-amber-300 rounded-xl p-5 hover:border-amber-500 hover:shadow-md transition group"
          >
            <div className="flex items-start gap-4">
              <div className="text-3xl animate-pulse">🔔</div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-bold text-amber-900 uppercase tracking-wider">
                    Action Required
                  </span>
                  <span className="px-2 py-0.5 rounded-full bg-amber-200 text-amber-900 text-[11px] font-bold">
                    {notif.unread}
                  </span>
                </div>
                <h3 className="text-lg font-extrabold text-amber-900">
                  มี <span className="tabular-nums">{notif.unread}</span> แจ้งเตือนยังไม่อ่าน
                </h3>
                <div className="mt-2 flex flex-wrap gap-2">
                  {Object.entries(notif.by_category)
                    .filter(([, c]) => c > 0)
                    .map(([key, c]) => {
                      const info = CATEGORY_LABELS[key];
                      if (!info) return null;
                      return (
                        <span
                          key={key}
                          className="inline-flex items-center gap-1 px-2 py-1 rounded bg-white border border-amber-200 text-[11px] font-semibold text-amber-900"
                        >
                          <span>{info.icon}</span>
                          <span>{info.label}</span>
                          <span className="ml-1 font-mono text-amber-700">×{c}</span>
                        </span>
                      );
                    })}
                </div>
              </div>
              <div className="text-amber-700 group-hover:text-amber-900 font-bold text-2xl transition">
                →
              </div>
            </div>
          </Link>
        )}

        {data && (
          <>
            <section className="mb-8">
              <h2 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
                ผู้ใช้งานในระบบ
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <StatsCard
                  label="ผู้ใช้ทั้งหมด"
                  value={data.users.total}
                  sub={`ใช้งานได้ ${data.users.active} คน`}
                  icon="👥"
                  tone="brand"
                />
                <StatsCard
                  label="นักศึกษา"
                  value={counts?.student ?? "—"}
                  sub="student"
                  icon="🎓"
                />
                <StatsCard
                  label="อาจารย์"
                  value={counts?.teacher ?? "—"}
                  sub="teacher"
                  icon="👨‍🏫"
                />
                <StatsCard
                  label="เจ้าหน้าที่"
                  value={counts?.staff ?? "—"}
                  sub={`+ admin ${counts?.admin ?? 0}`}
                  icon="👔"
                />
              </div>
            </section>

            <section className="mb-8">
              <h2 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
                ระบบย่อย
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <StatsCard
                  label="ทั้งหมด"
                  value={data.subsystems.total}
                  sub="subsystems registered"
                  icon="🧩"
                />
                <StatsCard
                  label="พร้อมใช้งาน"
                  value={data.subsystems.active}
                  sub="active"
                  icon="✅"
                  tone="good"
                />
                <StatsCard
                  label="รออนุมัติ"
                  value={data.subsystems.pending}
                  sub="pending approval"
                  icon="⏳"
                  tone="warn"
                />
              </div>
            </section>

            <section>
              <h2 className="text-xs font-bold text-ink-500 uppercase tracking-wider mb-3">
                Login + ML decision
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <StatsCard
                  label="Login ทั้งหมด"
                  value={data.logins.total}
                  sub="ทุก session ที่ผ่าน ML scoring"
                  icon="🔑"
                />
                <StatsCard
                  label="ถูก block"
                  value={data.logins.blocked}
                  sub="ML decision = block"
                  icon="🚫"
                  tone={data.logins.blocked > 0 ? "danger" : "default"}
                />
              </div>
            </section>
          </>
        )}
      </main>
    </>
  );
}
