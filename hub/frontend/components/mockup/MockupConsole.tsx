"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";

export const MOCKUP_SCREENS: Record<string, { label: string; endpoint?: string }> = {
  dashboard: { label: "ภาพรวม / Dashboard", endpoint: "/api/proxy/admin/overview" },
  users: { label: "ผู้ใช้งาน / Users", endpoint: "/api/proxy/admin/users/?limit=200" },
  "user-detail": { label: "รายละเอียดผู้ใช้ / User Detail", endpoint: "/api/proxy/admin/users/?limit=1" },
  subsystems: { label: "ระบบย่อย / Subsystems", endpoint: "/api/proxy/admin/subsystems" },
  "subsystem-detail": { label: "รายละเอียดระบบ / Subsystem Detail", endpoint: "/api/proxy/admin/subsystems" },
  requests: { label: "คำขอสิทธิ์ / Access Requests", endpoint: "/api/proxy/admin/change-requests?status=pending&limit=100" },
  permissions: { label: "สิทธิ์และขอบเขต / Permissions", endpoint: "/api/proxy/admin/subsystems" },
  risk: { label: "ความเสี่ยง / Risk & Security", endpoint: "/api/proxy/admin/ml/overview?days=7&sort=recent&limit=50" },
  "risk-detail": { label: "รายละเอียดความเสี่ยง / Risk Detail", endpoint: "/api/proxy/admin/ml/overview?days=7&sort=score&limit=1" },
  audit: { label: "บันทึกกิจกรรม / Audit Logs", endpoint: "/api/proxy/admin/audit?skip=0&limit=50" },
  settings: { label: "ตั้งค่า / Settings" },
};

type Json = Record<string, unknown> | unknown[] | null;

const nav = ["dashboard", "users", "subsystems", "requests", "permissions", "risk", "audit", "settings"];

function rowsFrom(value: Json): Record<string, unknown>[] {
  if (Array.isArray(value)) return value.filter((x): x is Record<string, unknown> => !!x && typeof x === "object");
  if (!value || typeof value !== "object") return [];
  for (const key of ["items", "users", "subsystems", "requests", "logs", "events", "anomalies", "results", "data"]) {
    const candidate = (value as Record<string, unknown>)[key];
    if (Array.isArray(candidate)) return candidate.filter((x): x is Record<string, unknown> => !!x && typeof x === "object");
  }
  const nestedData = (value as Record<string, unknown>).data;
  if (nestedData && typeof nestedData === "object" && !Array.isArray(nestedData)) {
    for (const key of ["top_anomalies", "items", "events"]) {
      const candidate = (nestedData as Record<string, unknown>)[key];
      if (Array.isArray(candidate)) return candidate.filter((x): x is Record<string, unknown> => !!x && typeof x === "object");
    }
  }
  return [];
}

function text(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "boolean") return value ? "ใช่ / Yes" : "ไม่ / No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function MockupConsole({ screen }: { screen: string }) {
  const config = MOCKUP_SCREENS[screen];
  const [data, setData] = useState<Json>(null);
  const [loading, setLoading] = useState(Boolean(config.endpoint));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!config.endpoint) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetch(config.endpoint, { credentials: "include", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then(setData)
      .catch((reason) => {
        if (reason.name !== "AbortError") setError(reason.message || "โหลดข้อมูลไม่สำเร็จ");
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [config.endpoint]);

  const rows = useMemo(() => rowsFrom(data), [data]);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="flex min-h-screen">
        <Sidebar screen={screen} />
        <div className="min-w-0 flex-1">
          <Topbar />
          <main className="mx-auto max-w-[1600px] space-y-5 p-6 lg:p-8">
            <Header title={config.label} endpoint={config.endpoint} />
            {error && <Notice tone="red">ไม่สามารถอ่าน API: {error}</Notice>}
            {loading ? <Loading /> : <Screen screen={screen} data={data} rows={rows} />}
          </main>
        </div>
      </div>
    </div>
  );
}

function Sidebar({ screen }: { screen: string }) {
  const pathname = usePathname();
  return (
    <aside className="sticky top-0 hidden h-screen w-72 shrink-0 flex-col bg-[#071b45] text-white lg:flex">
      <div className="border-b border-white/10 p-6">
        <div className="flex items-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-xl bg-cyan-500 text-xl font-black">H</div>
          <div><div className="font-extrabold">Central Auth Hub</div><div className="text-xs text-slate-300">University IAM Platform</div></div>
        </div>
      </div>
      <nav className="flex-1 space-y-1 overflow-y-auto p-3">
        {nav.map((slug) => {
          const active = screen === slug || (screen.endsWith("-detail") && screen.startsWith(slug.replace("s", "")));
          return <Link key={slug} href={`/ui-mockup/${slug}`} className={`block rounded-xl px-4 py-3 text-sm font-semibold ${active ? "bg-blue-600 shadow-lg" : "text-slate-300 hover:bg-white/10"}`}>{MOCKUP_SCREENS[slug].label}</Link>;
        })}
      </nav>
      <div className="border-t border-white/10 p-5 text-xs text-slate-400">OAuth 2.0 • OIDC • PKCE<br />RBAC • ML Risk Analysis</div>
    </aside>
  );
}

function Topbar() {
  return <header className="sticky top-0 z-20 flex h-16 items-center border-b bg-white px-6"><div className="w-full max-w-xl rounded-xl border px-4 py-2.5 text-sm text-slate-400">ค้นหา / Search...</div><div className="ml-auto flex items-center gap-3"><span>🔔</span><span className="grid h-10 w-10 place-items-center rounded-full bg-blue-600 text-sm font-bold text-white">AD</span><div className="hidden text-sm md:block"><b>Administrator</b><div className="text-xs text-slate-500">System Admin</div></div></div></header>;
}

function Header({ title, endpoint }: { title: string; endpoint?: string }) {
  return <div className="flex flex-wrap items-end gap-3"><div><h1 className="text-2xl font-black lg:text-3xl">{title}</h1><p className="mt-2 text-sm text-slate-500">Mockup ที่แสดงข้อมูลจากระบบจริงเท่านั้น / Live system data</p></div>{endpoint && <code className="ml-auto rounded-lg bg-slate-100 px-3 py-2 text-xs text-slate-500">{endpoint}</code>}</div>;
}

function Screen({ screen, data, rows }: { screen: string; data: Json; rows: Record<string, unknown>[] }) {
  if (screen === "dashboard") return <Dashboard data={data} />;
  if (screen === "settings") return <Settings />;
  if (screen.endsWith("-detail")) return <Detail screen={screen} row={rows[0]} />;
  if (screen === "permissions") return <Permissions rows={rows} />;
  return <ListScreen screen={screen} rows={rows} />;
}

function Dashboard({ data }: { data: Json }) {
  const obj = data && !Array.isArray(data) ? data as Record<string, unknown> : {};
  const users = obj.users as Record<string, unknown> | undefined;
  const subsystems = obj.subsystems as Record<string, unknown> | undefined;
  const logins = obj.logins as Record<string, unknown> | undefined;
  return <>
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <Stat label="ผู้ใช้ทั้งหมด / Total Users" value={text(users?.total)} color="blue" />
      <Stat label="ผู้ใช้ที่ใช้งาน / Active Users" value={text(users?.active)} color="green" />
      <Stat label="ระบบย่อย / Subsystems" value={text(subsystems?.total)} color="cyan" />
      <Stat label="ถูกบล็อก / Blocked Logins" value={text(logins?.blocked)} color="red" />
    </div>
    <div className="grid gap-5 xl:grid-cols-[2fr_1fr]">
      <Card title="กิจกรรมการเข้าสู่ระบบ / Login Activity"><Chart /></Card>
      <Card title="Risk-Based Authentication"><Donut value={text(logins?.blocked)} /></Card>
    </div>
    <Card title="ข้อมูลภาพรวมจาก API / Live Overview"><ObjectView value={obj} /></Card>
  </>;
}

function ListScreen({ screen, rows }: { screen: string; rows: Record<string, unknown>[] }) {
  const labels: Record<string, string> = { users: "รายชื่อผู้ใช้ / User Directory", subsystems: "สถานะระบบย่อย / Subsystem Health", requests: "คำขอที่รอดำเนินการ / Pending Requests", risk: "เหตุการณ์ความเสี่ยง / Risk Events", audit: "Append-only Audit Events" };
  return <Card title={labels[screen] || MOCKUP_SCREENS[screen].label}><DataTable rows={rows} /></Card>;
}

function Detail({ screen, row }: { screen: string; row?: Record<string, unknown> }) {
  if (!row) return <Empty />;
  return <div className="grid gap-5 xl:grid-cols-[2fr_1fr]"><Card title="รายละเอียดจากระบบจริง / Live Detail"><ObjectView value={row} /></Card><Card title={screen === "risk-detail" ? "คำอธิบายโมเดล / Model Explanation" : "สถานะ / Status"}><ObjectView value={pickSignals(row)} /></Card></div>;
}

function Permissions({ rows }: { rows: Record<string, unknown>[] }) {
  return <div className="grid gap-5 xl:grid-cols-[260px_1fr]"><Card title="ระบบย่อย / Subsystems">{rows.length ? rows.map((row, i) => <div key={i} className="mb-2 rounded-xl bg-slate-50 p-3 text-sm font-semibold">{text(row.name || row.display_name || row.client_id)}</div>) : <Empty />}</Card><Card title="ขอบเขตที่ระบบประกาศ / Registered Scopes"><DataTable rows={rows.map((row) => ({ subsystem: row.name || row.client_id, scopes: row.scopes || row.allowed_scopes || [] }))} /></Card></div>;
}

function Settings() {
  return <><Notice tone="amber">ค่าที่แสดงในหน้า Mockup นี้เป็นแบบอ่านอย่างเดียว และไม่ส่งการเปลี่ยนแปลงไป Backend</Notice><div className="grid gap-5 xl:grid-cols-2"><Card title="Session Security"><ReadOnlySetting label="SESSION_COOKIE_SECURE" value="อ่านจาก Environment ของ Backend" /><ReadOnlySetting label="HttpOnly / SameSite" value="อ่านจาก Session Configuration" /></Card><Card title="Token & Risk Policy"><ReadOnlySetting label="Access Token Lifetime" value="อ่านจาก Backend Settings" /><ReadOnlySetting label="Risk Threshold" value="อ่านจาก Risk Engine Policy" /></Card></div></>;
}

function DataTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows.length) return <Empty />;
  const columns = Array.from(new Set(rows.slice(0, 10).flatMap(Object.keys))).slice(0, 8);
  return <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-sm"><thead><tr className="border-b bg-slate-50">{columns.map((c) => <th key={c} className="px-4 py-3 text-xs uppercase text-slate-500">{c}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={i} className="border-b last:border-0">{columns.map((c) => <td key={c} className="max-w-[260px] truncate px-4 py-4">{text(row[c])}</td>)}</tr>)}</tbody></table></div>;
}

function ObjectView({ value }: { value: unknown }) {
  if (!value || typeof value !== "object") return <Empty />;
  return <div className="grid gap-3 md:grid-cols-2">{Object.entries(value as Record<string, unknown>).map(([k, v]) => <div key={k} className="rounded-xl border bg-slate-50 p-4"><div className="text-xs font-bold uppercase text-slate-500">{k}</div><div className="mt-2 break-words text-sm font-semibold">{text(v)}</div></div>)}</div>;
}

function pickSignals(row: Record<string, unknown>) {
  const result: Record<string, unknown> = {};
  for (const key of ["risk_score", "anomaly_score", "decision", "explanation", "shap_values", "status", "health", "scopes"]) if (key in row) result[key] = row[key];
  return Object.keys(result).length ? result : row;
}

function Card({ title, children }: { title: string; children: React.ReactNode }) { return <section className="overflow-hidden rounded-2xl border bg-white shadow-sm"><div className="border-b px-5 py-4 font-extrabold">{title}</div><div className="p-5">{children}</div></section>; }
function Stat({ label, value, color }: { label: string; value: string; color: string }) { const colors: Record<string, string> = { blue: "text-blue-600 bg-blue-50", green: "text-emerald-600 bg-emerald-50", cyan: "text-cyan-600 bg-cyan-50", red: "text-red-600 bg-red-50" }; return <div className="rounded-2xl border bg-white p-5 shadow-sm"><div className="text-sm font-semibold text-slate-600">{label}</div><div className={`mt-3 inline-flex rounded-xl px-3 py-1 text-3xl font-black ${colors[color]}`}>{value}</div></div>; }
function Chart() { return <svg viewBox="0 0 800 230" className="h-64 w-full rounded-xl bg-gradient-to-b from-blue-50 to-white"><polyline points="0,180 80,145 160,190 240,110 320,150 400,70 480,120 560,45 640,115 720,145 800,180" fill="none" stroke="#2563eb" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" /></svg>; }
function Donut({ value }: { value: string }) { return <div className="mx-auto grid h-56 w-56 place-items-center rounded-full bg-[conic-gradient(#14b8a6_0_82%,#e2e8f0_82%)]"><div className="grid h-40 w-40 place-items-center rounded-full bg-white text-center"><div><div className="text-3xl font-black">{value}</div><div className="text-sm text-slate-500">Blocked</div></div></div></div>; }
function Empty() { return <div className="rounded-xl border border-dashed p-10 text-center text-sm text-slate-500">ไม่มีข้อมูลจาก API / No live data</div>; }
function Loading() { return <div className="grid min-h-[420px] place-items-center"><div className="text-sm font-semibold text-slate-500">กำลังโหลดข้อมูลจริง / Loading live data...</div></div>; }
function Notice({ tone, children }: { tone: "red" | "amber"; children: React.ReactNode }) { return <div className={`rounded-xl border p-4 text-sm ${tone === "red" ? "border-red-200 bg-red-50 text-red-700" : "border-amber-200 bg-amber-50 text-amber-800"}`}>{children}</div>; }
function ReadOnlySetting({ label, value }: { label: string; value: string }) { return <div className="flex justify-between gap-5 border-b py-4 text-sm last:border-0"><b>{label}</b><span className="text-right text-slate-500">{value}</span></div>; }
