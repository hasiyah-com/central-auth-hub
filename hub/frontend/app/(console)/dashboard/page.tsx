"use client";

/**
 * SOC Dashboard — ธีมกรมท่า (navy) + cyan, ศูนย์เฝ้าระวังการยืนยันตัวตน.
 * Signature: AuthTopologyMap — แผนที่โลก + เส้น auth flow เข้า Hub + node ระบบย่อย.
 * ข้อมูลจริงทั้งหมด: /admin/overview, /admin/users/count, /admin/dashboard/map,
 * /admin/notifications/count. ฟังก์ชันเดิมครบ (health check, notif, auth-policy).
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { clientFetch } from "@/lib/api";
import { LoginMethodsCard } from "./_components/LoginMethodsCard";
import { AuthTopologyMap } from "./_components/AuthTopologyMap";

type Overview = {
  users: { total: number; active: number };
  subsystems: { total: number; active: number; pending: number };
  logins: { total: number; blocked: number };
};

type UserCount = Record<string, number>;

type NotifCount = {
  total: number;
  unread?: number;
  by_category: {
    approval_requests: number;
    ml_anomaly: number;
    api_alerts: number;
    subsystem_health: number;
  };
};

type MapData = {
  geo: { country: string; risk: "green" | "yellow" | "red"; count: number }[];
  decisions: Record<string, number>;
  subsystems: { id: string; name: string; status: string; health: string | null; latency_ms: number | null }[];
  active_now: number;
};

const CATEGORY_LABELS: Record<string, { label: string; icon: string }> = {
  approval_requests: { label: "คำขอ Approve", icon: "📋" },
  ml_anomaly: { label: "ML Anomaly", icon: "🧠" },
  api_alerts: { label: "API Alerts", icon: "🛡️" },
  subsystem_health: { label: "Subsystem ล่ม", icon: "🟢" },
};

type HealthCheckResult = {
  ok: boolean;
  subsystems?: number;
};

const HEALTH_DOT: Record<string, string> = {
  online: "bg-emerald-400",
  degraded: "bg-amber-400",
  down: "bg-rose-400",
};

// จัดกลุ่ม decision → 3 ระดับสำหรับ bar
function decisionGroups(d: Record<string, number>) {
  const g = { allow: 0, watch: 0, block: 0 };
  for (const [k, v] of Object.entries(d)) {
    if (k === "allow" || k === "mfa_passed") g.allow += v;
    else if (k.includes("block")) g.block += v;
    else g.watch += v; // warn / challenge / would_*
  }
  return g;
}

export default function DashboardPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [counts, setCounts] = useState<UserCount | null>(null);
  const [notif, setNotif] = useState<NotifCount | null>(null);
  const [map, setMap] = useState<MapData | null>(null);
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
      clientFetch<NotifCount>("/admin/notifications/count")
        .then(setNotif)
        .catch(() => {});
      clientFetch<MapData>("/admin/dashboard/map").then(setMap).catch(() => {});
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
      clientFetch<MapData>("/admin/dashboard/map").catch(() => null),
    ])
      .then(([ov, ct, nc, mp]) => {
        setData(ov);
        setCounts(ct);
        if (nc) setNotif(nc);
        if (mp) setMap(mp);
      })
      .catch((e) => setError(e.detail || "โหลดข้อมูลไม่สำเร็จ"));

    const t = setInterval(() => {
      clientFetch<NotifCount>("/admin/notifications/count")
        .then(setNotif)
        .catch(() => {});
      clientFetch<MapData>("/admin/dashboard/map").then(setMap).catch(() => {});
    }, 30_000);
    return () => clearInterval(t);
  }, []);

  const dec = map ? decisionGroups(map.decisions) : null;
  const decTotal = dec ? dec.allow + dec.watch + dec.block : 0;
  const onlineSubs = map?.subsystems.filter((s) => s.health === "online").length ?? 0;
  const downSubs = map?.subsystems.filter((s) => s.health === "down").length ?? 0;

  return (
    <>
      <Topbar title="ภาพรวมระบบ" />
      {/* พื้นหลัง navy ครอบทั้งหน้า dashboard */}
      <main className="min-h-[calc(100vh-57px)] bg-[#0b1530] px-6 py-6 lg:px-8">
        <div className="max-w-7xl mx-auto w-full space-y-5">
          {error && (
            <div className="p-4 rounded-lg bg-rose-950/60 border border-rose-800 text-rose-200 text-sm">
              {error}
            </div>
          )}

          {/* ── header row: ชื่อศูนย์ + health check ── */}
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <div className="text-[11px] font-mono tracking-[0.25em] text-cyan-400/80 uppercase">
                Central Auth Hub · Security Monitor
              </div>
              <h1 className="text-xl font-extrabold text-white mt-0.5">
                ศูนย์เฝ้าระวังการยืนยันตัวตน
              </h1>
            </div>
            <div className="ml-auto flex items-center gap-3">
              {map && (
                <div className="hidden sm:flex items-center gap-2 text-xs font-mono text-slate-400">
                  <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                  {map.active_now} sessions online
                </div>
              )}
              <button
                onClick={runHealthCheckNow}
                disabled={hcBusy}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-cyan-500/15 border border-cyan-500/40 hover:bg-cyan-500/25 disabled:opacity-40 text-cyan-300 text-sm font-bold transition"
              >
                {hcBusy ? "กำลังตรวจ…" : "🩺 เช็คสุขภาพระบบ"}
              </button>
            </div>
          </div>

          {hcResult && hcResult.ok && (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-950/50 border border-emerald-700/60 text-emerald-300 text-xs">
              ✓ ตรวจเสร็จ — Hub + {hcResult.subsystems} subsystem
              <Link href="/notifications" className="ml-1 font-bold underline hover:no-underline">
                รายงาน →
              </Link>
            </div>
          )}
          {hcError && (
            <div className="px-3 py-2 rounded-lg bg-rose-950/50 border border-rose-800 text-rose-300 text-xs">
              ✗ {hcError}
            </div>
          )}

          {/* ── notifications banner ── */}
          {notif && (notif.unread ?? 0) > 0 && (
            <Link
              href="/notifications"
              className="block rounded-xl border border-amber-500/50 bg-amber-500/10 p-4 hover:bg-amber-500/15 transition group"
            >
              <div className="flex items-center gap-3">
                <span className="text-2xl">🔔</span>
                <div className="flex-1">
                  <div className="text-sm font-extrabold text-amber-300">
                    มี {notif.unread} แจ้งเตือนยังไม่อ่าน
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {Object.entries(notif.by_category)
                      .filter(([, c]) => c > 0)
                      .map(([key, c]) => {
                        const info = CATEGORY_LABELS[key];
                        if (!info) return null;
                        return (
                          <span
                            key={key}
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-500/15 border border-amber-500/30 text-[11px] font-semibold text-amber-200"
                          >
                            {info.icon} {info.label}
                            <span className="font-mono">×{c}</span>
                          </span>
                        );
                      })}
                  </div>
                </div>
                <span className="text-amber-400 group-hover:translate-x-1 transition text-xl">→</span>
              </div>
            </Link>
          )}

          {/* ── KPI strip ── */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
            {[
              { label: "ผู้ใช้ทั้งหมด", value: data?.users.total ?? "—", sub: `active ${data?.users.active ?? "—"}` },
              { label: "นักศึกษา", value: counts?.student ?? "—", sub: "student" },
              { label: "บุคลากร", value: counts ? (counts.teacher ?? 0) + (counts.staff ?? 0) + (counts.admin ?? 0) : "—", sub: "teacher · staff · admin" },
              { label: "ระบบย่อย", value: data?.subsystems.active ?? "—", sub: `pending ${data?.subsystems.pending ?? 0}` },
              { label: "Login ทั้งหมด", value: data?.logins.total ?? "—", sub: "ผ่าน RBA scoring" },
              {
                label: "ถูกบล็อก",
                value: data?.logins.blocked ?? "—",
                sub: "decision = block",
                danger: (data?.logins.blocked ?? 0) > 0,
              },
            ].map((c) => (
              <div
                key={c.label}
                className="rounded-xl border border-slate-700/60 bg-slate-900/50 px-4 py-3"
              >
                <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400">
                  {c.label}
                </div>
                <div
                  className={`text-2xl font-extrabold tabular-nums mt-0.5 ${
                    c.danger ? "text-rose-400" : "text-white"
                  }`}
                >
                  {c.value}
                </div>
                <div className="text-[10px] text-slate-500">{c.sub}</div>
              </div>
            ))}
          </div>

          {/* ── main: map + side panel ── */}
          <div className="grid lg:grid-cols-3 gap-5">
            {/* world map — signature */}
            <section className="lg:col-span-2 rounded-xl border border-slate-700/60 bg-slate-900/50 overflow-hidden">
              <div className="px-5 py-3.5 border-b border-slate-700/60 flex items-center justify-between">
                <h2 className="text-sm font-bold text-slate-200">
                  แผนที่การยืนยันตัวตน
                  <span className="ml-2 text-[10px] font-mono text-slate-500 uppercase">
                    login origins · 30 วัน
                  </span>
                </h2>
                <div className="flex items-center gap-3 text-[10px] font-mono text-slate-400">
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-emerald-400" /> online
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-amber-400" /> degraded
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-rose-400" /> down
                  </span>
                </div>
              </div>
              <div className="p-2">
                {map ? (
                  <AuthTopologyMap geo={map.geo} subsystems={map.subsystems} />
                ) : (
                  <div className="h-72 grid place-items-center text-slate-500 text-sm">
                    กำลังโหลดแผนที่…
                  </div>
                )}
              </div>
            </section>

            {/* side panel: topology list + decisions */}
            <div className="space-y-5">
              {/* subsystem link status */}
              <section className="rounded-xl border border-slate-700/60 bg-slate-900/50">
                <div className="px-5 py-3.5 border-b border-slate-700/60 flex items-center justify-between">
                  <h2 className="text-sm font-bold text-slate-200">การเชื่อมต่อระบบย่อย</h2>
                  <span className="text-[10px] font-mono text-slate-500">
                    {onlineSubs} online{downSubs > 0 && ` · ${downSubs} down`}
                  </span>
                </div>
                <div className="p-3 space-y-1.5">
                  {!map || map.subsystems.length === 0 ? (
                    <div className="text-sm text-slate-500 text-center py-4">
                      ยังไม่มีระบบย่อย
                    </div>
                  ) : (
                    map.subsystems
                      .filter((s) => s.status === "active")
                      .map((s) => (
                        <Link
                          key={s.id}
                          href={`/subsystems/${s.id}`}
                          className="flex items-center gap-3 px-3 py-2 rounded-lg border border-slate-700/50 hover:border-cyan-500/50 hover:bg-cyan-500/5 transition text-xs"
                        >
                          <span
                            className={`w-2 h-2 rounded-full shrink-0 ${
                              HEALTH_DOT[s.health || ""] || "bg-slate-500"
                            }`}
                          />
                          <span className="flex-1 text-slate-200 font-medium truncate">
                            {s.name}
                          </span>
                          <span className="font-mono text-slate-500">
                            {s.latency_ms != null ? `${s.latency_ms}ms` : s.health || "—"}
                          </span>
                        </Link>
                      ))
                  )}
                </div>
              </section>

              {/* decision distribution */}
              <section className="rounded-xl border border-slate-700/60 bg-slate-900/50 p-5">
                <h2 className="text-sm font-bold text-slate-200 mb-3">
                  ผลตัดสิน RBA
                  <span className="ml-2 text-[10px] font-mono text-slate-500 uppercase">30 วัน</span>
                </h2>
                {dec && decTotal > 0 ? (
                  <>
                    <div className="flex h-2.5 rounded-full overflow-hidden bg-slate-800">
                      <div className="bg-emerald-400" style={{ width: `${(dec.allow / decTotal) * 100}%` }} />
                      <div className="bg-amber-400" style={{ width: `${(dec.watch / decTotal) * 100}%` }} />
                      <div className="bg-rose-400" style={{ width: `${(dec.block / decTotal) * 100}%` }} />
                    </div>
                    <div className="mt-3 space-y-1.5 text-xs">
                      {[
                        { label: "อนุญาต (allow)", v: dec.allow, dot: "bg-emerald-400" },
                        { label: "เฝ้าระวัง (warn / challenge)", v: dec.watch, dot: "bg-amber-400" },
                        { label: "บล็อก (block)", v: dec.block, dot: "bg-rose-400" },
                      ].map((r) => (
                        <div key={r.label} className="flex items-center gap-2">
                          <span className={`w-2 h-2 rounded-full ${r.dot}`} />
                          <span className="text-slate-300 flex-1">{r.label}</span>
                          <span className="font-mono text-slate-400 tabular-nums">{r.v}</span>
                          <span className="font-mono text-slate-600 w-10 text-right">
                            {Math.round((r.v / decTotal) * 100)}%
                          </span>
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="text-sm text-slate-500 text-center py-3">ยังไม่มีข้อมูล</div>
                )}
                <Link
                  href="/ml"
                  className="mt-3 inline-block text-[11px] font-bold text-cyan-400 hover:text-cyan-300"
                >
                  ดูรายละเอียด ML →
                </Link>
              </section>
            </div>
          </div>

          {/* ── auth policy (การ์ดเดิม — พื้นขาว ตัดกับ navy อ่านง่าย) ── */}
          <LoginMethodsCard />
        </div>
      </main>
    </>
  );
}
