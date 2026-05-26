"use client";

import { useEffect, useState } from "react";
import { Topbar } from "@/components/Topbar";
import { StatsCard } from "@/components/StatsCard";
import { clientFetch } from "@/lib/api";

type Overview = {
  users: { total: number; active: number };
  subsystems: { total: number; active: number; pending: number };
  logins: { total: number; blocked: number };
};

type UserCount = Record<string, number>;

export default function DashboardPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [counts, setCounts] = useState<UserCount | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      clientFetch<Overview>("/admin/overview"),
      clientFetch<UserCount>("/admin/users/count"),
    ])
      .then(([ov, ct]) => {
        setData(ov);
        setCounts(ct);
      })
      .catch((e) => setError(e.detail || "โหลดข้อมูลไม่สำเร็จ"));
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
