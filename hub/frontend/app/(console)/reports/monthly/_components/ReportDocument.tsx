"use client";

/**
 * เนื้อหารายงานสรุปประจำเดือน (ส่วนที่พิมพ์ออก) — render จาก data อย่างเดียว ไม่ fetch เอง
 * สรุปผู้บริหาร / ข้อเสนอแนะ / บทสรุป ร่างโดยกฎฝั่ง backend จากตัวเลขจริง —
 *   แก้ถ้อยคำบนหน้าได้ก่อนพิมพ์ (ไม่บันทึก เปลี่ยนเดือนแล้วกลับเป็นร่างเดิม)
 */

import { useMemo, useState, type ReactNode } from "react";
import type { Level, Priority, Report } from "../_types";

type RecRow = Report["recommendations"][number] & { id: string };

const LEVEL_LABEL: Record<Level, string> = { critical: "วิกฤต", warn: "ติดตาม", info: "ข้อมูล" };
const PRIORITY_LABEL: Record<Priority, string> = { high: "สูง", medium: "กลาง", low: "ต่ำ" };
const PRIORITY_TONE: Record<Priority, Level> = { high: "critical", medium: "warn", low: "info" };
const PRIORITY_NEXT: Record<Priority, Priority> = { high: "medium", medium: "low", low: "high" };
const METHOD_LABEL: Record<string, string> = {
  google: "Google",
  passkey: "Passkey",
  totp: "TOTP",
  line: "LINE",
};
const UNAVAILABLE_TEXT: Record<string, string> = {
  subsystem_uptime:
    "Uptime จริงของระบบ — ระบบเก็บผลตรวจสุขภาพแบบละเอียดย้อนหลังเพียง 24 ชั่วโมง ตัวเลขความพร้อมใช้งานในรายงานนี้จึงมาจากผลสุ่มตรวจวันละ 3 ครั้ง (เช้า บ่าย เย็น) ไม่ใช่ uptime ต่อเนื่อง",
  resource_usage: "การใช้ทรัพยากรของเซิร์ฟเวอร์ (CPU / Memory / Disk) — ระบบยังไม่ได้เก็บข้อมูลนี้",
};

export function thaiMonth(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString("th-TH", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

const fmt = (v: number) => v.toLocaleString("th-TH", { maximumFractionDigits: 1 });
const pctText = (v: number | null) => (v === null ? "—" : `${v}%`);
const msText = (v: number | null) => (v === null ? "—" : `${fmt(v)} ms`);
const share = (part: number, total: number) =>
  total ? `${((part / total) * 100).toFixed(1)}%` : "—";

function bkkDateText(d: Date): string {
  return d.toLocaleDateString("th-TH", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Bangkok",
  });
}

/** ช่วงข้อมูล — เดือนที่ยังไม่จบแสดงถึงวันที่สร้างรายงาน (ไม่อ้างว่าครบเดือน) */
function rangeText(r: Report["range"]): string {
  const from = new Date(r.from);
  const to = new Date(new Date(r.to).getTime() - 1);
  const now = new Date();
  const partial = to > now;
  return `${bkkDateText(from)} – ${bkkDateText(partial ? now : to)}${
    partial ? " (เดือนยังไม่สิ้นสุด)" : ""
  }`;
}

function dayText(d: string): string {
  return new Date(`${d}T00:00:00Z`).toLocaleDateString("th-TH", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

function countryText(code: string | null): string {
  if (!code) return "ไม่ทราบ (IP ภายใน / ไม่มีข้อมูล)";
  try {
    return new Intl.DisplayNames(["th"], { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
}

/** % เทียบเดือนก่อน — worseWhenUp: ตัวชี้วัดความเสี่ยง เพิ่มขึ้น = แย่ */
function Delta({ pct, worseWhenUp }: { pct: number | null; worseWhenUp?: boolean }) {
  if (pct === null) return <small className="mono">ไม่มีข้อมูลเทียบ</small>;
  const up = pct > 0;
  const tone = pct === 0 ? "" : up === !!worseWhenUp ? "bad" : "good";
  return (
    <small className={`mono cx-delta ${tone}`}>
      {up ? "+" : ""}
      {pct}% เทียบเดือนก่อน
    </small>
  );
}

function Tag({ tone, children }: { tone: Level; children: ReactNode }) {
  return <span className={`cx-tag ${tone}`}>{children}</span>;
}

function Section({
  no,
  title,
  en,
  flush,
  children,
}: {
  no: string;
  title: string;
  en: string;
  flush?: boolean;
  children: ReactNode;
}) {
  return (
    <section className="cx-rep-section">
      <h3>
        <span className="mono">{no}</span>
        {title}
        <small>{en}</small>
      </h3>
      <div className={`cx-rep-body${flush ? " flush" : ""}`}>{children}</div>
    </section>
  );
}

/** ข้อความที่แก้ได้ก่อนพิมพ์ — uncontrolled: React ไม่เขียนทับสิ่งที่พิมพ์ตราบที่ text เดิม */
function Editable({ text, placeholder }: { text: string; placeholder?: string }) {
  return (
    <div
      className="cx-rep-text"
      contentEditable
      suppressContentEditableWarning
      spellCheck={false}
      data-placeholder={placeholder}
    >
      {text}
    </div>
  );
}

export function ReportDocument({
  month,
  data,
  error,
}: {
  month: string;
  data: Report | null;
  error: string | null;
}) {
  // เวลาที่สร้างรายงาน — คำนวณใหม่ทุกครั้งที่ได้ข้อมูลเดือนใหม่
  const generatedAt = useMemo(
    () =>
      data
        ? new Date().toLocaleString("th-TH", {
            timeZone: "Asia/Bangkok",
            dateStyle: "long",
            timeStyle: "short",
          })
        : "—",
    [data]
  );

  return (
    <main className="cx-document cx-report cx-rep">
      {error && <div className="cx-msg err">{error}</div>}

      <header className="cx-report-head">
        <div>
          <span className="mono">central auth hub · monthly report</span>
          <h2>รายงานสรุปประจำเดือน{thaiMonth(month)}</h2>
        </div>
        <dl>
          <div>
            <dt>ช่วงข้อมูล</dt>
            <dd>{data ? rangeText(data.range) : "—"}</dd>
          </div>
          <div>
            <dt>เทียบกับ</dt>
            <dd>{data ? thaiMonth(data.previous.month) : "—"}</dd>
          </div>
          <div>
            <dt>สร้างเมื่อ</dt>
            <dd>{generatedAt}</dd>
          </div>
        </dl>
      </header>

      {!data && !error && (
        <div className="cx-empty">
          <strong>กำลังโหลดรายงาน…</strong>
        </div>
      )}

      {/* key = เดือน → เปลี่ยนเดือนแล้วข้อความที่แก้และข้อเสนอแนะกลับเป็นร่างของเดือนนั้น */}
      {data && <ReportBody key={data.month} data={data} />}
    </main>
  );
}

function ReportBody({ data }: { data: Report }) {
  const [recs, setRecs] = useState<RecRow[]>(() =>
    data.recommendations.map((x, i) => ({ ...x, id: `${data.month}-${i}` }))
  );

  const maxDay = useMemo(() => Math.max(...data.daily.map((d) => d.total), 1), [data]);

  // ความพร้อมใช้งานรวม = สถานะปกติ / จำนวนการตรวจทั้งหมด (ทุกระบบรวมกัน)
  const availability = useMemo(() => {
    const samples = data.availability.units.reduce((s, u) => s + u.samples, 0);
    const online = data.availability.units.reduce((s, u) => s + u.online, 0);
    return samples ? Math.round((online / samples) * 1000) / 10 : null;
  }, [data]);

  const kpis = [
    { k: "logins", label: "logins", v: fmt(data.logins.total), sub: <Delta pct={data.change_pct.logins} />, tone: "signal" },
    { k: "users", label: "unique users", v: fmt(data.logins.unique_users), sub: <Delta pct={data.change_pct.unique_users} />, tone: "" },
    { k: "blocked", label: "blocked", v: fmt(data.logins.blocked), sub: <Delta pct={data.change_pct.blocked} worseWhenUp />, tone: "danger" },
    { k: "challenged", label: "challenged", v: fmt(data.logins.challenged), sub: <Delta pct={data.change_pct.challenged} worseWhenUp />, tone: "warn" },
    { k: "incidents", label: "incidents", v: fmt(data.risk.incidents), sub: <Delta pct={data.change_pct.incidents} worseWhenUp />, tone: "danger" },
    {
      k: "availability",
      label: "availability (sampled)",
      v: pctText(availability),
      sub: <small className="mono">สุ่มตรวจ {fmt(data.availability.samples)} รอบ</small>,
      tone: "",
    },
    {
      k: "p95",
      label: "api latency p95",
      v: msText(data.api_overall.p95_ms),
      sub: <small className="mono">เฉลี่ย {msText(data.api_overall.avg_ms)}</small>,
      tone: "",
    },
    {
      k: "subsystems",
      label: "active subsystems",
      v: fmt(data.subsystem_status.active),
      sub: <small className="mono">รออนุมัติ {fmt(data.subsystem_status.pending)}</small>,
      tone: "",
    },
  ];

  return (
    <>
      <Section no="01" title="สรุปผู้บริหาร" en="Executive Summary">
        <Editable text={data.narrative.summary} />
        {data.findings.length > 0 && (
          <>
            <h4 className="cx-rep-sub">ข้อสังเกตสำคัญ</h4>
            <ol className="cx-rep-findings">
              {data.findings.map((f, i) => (
                <li key={`${f.code}-${i}`}>
                  <Tag tone={f.level}>{LEVEL_LABEL[f.level]}</Tag>
                  <span>{f.text}</span>
                </li>
              ))}
            </ol>
          </>
        )}
      </Section>

      <Section no="02" title="ตัวชี้วัดหลัก" en="Key Metrics">
        <div className="cx-kpis eight">
          {kpis.map((c) => (
            <article key={c.k} className={`cx-kpi${c.tone ? " " + c.tone : ""}`}>
              <span>{c.label}</span>
              <strong className="mono">{c.v}</strong>
              {c.sub}
            </article>
          ))}
        </div>
      </Section>

      <Section no="03" title="การใช้งานแต่ละระบบ" en="Usage by Subsystem" flush>
        {data.by_subsystem.length === 0 ? (
          <p className="cx-rep-empty">ไม่มีการเข้าสู่ระบบในเดือนนี้</p>
        ) : (
          <table className="cx-report-table">
            <thead>
              <tr>
                <th>ระบบ</th>
                <th className="num">เข้าสู่ระบบ</th>
                <th className="num">ผู้ใช้</th>
                <th className="num">ระงับ</th>
                <th className="num">อัตราระงับ</th>
                <th className="num">ยืนยันเพิ่ม</th>
                <th className="num">สัดส่วน</th>
              </tr>
            </thead>
            <tbody>
              {data.by_subsystem.map((s) => (
                <tr key={s.subsystem_id ?? "hub-direct"}>
                  <td>{s.name}</td>
                  <td className="num mono">{fmt(s.total)}</td>
                  <td className="num mono">{fmt(s.unique_users)}</td>
                  <td className="num mono">{fmt(s.blocked)}</td>
                  <td className="num mono">{pctText(s.block_rate)}</td>
                  <td className="num mono">{fmt(s.challenged)}</td>
                  <td className="num mono">{share(s.total, data.logins.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <h4 className="cx-rep-sub pad">ผลตรวจสุขภาพระบบ</h4>
        {data.availability.samples === 0 ? (
          <p className="cx-rep-empty">ไม่มีผลตรวจสุขภาพระบบในเดือนนี้</p>
        ) : (
          <table className="cx-report-table">
            <thead>
              <tr>
                <th>ระบบ</th>
                <th className="num">ตรวจ</th>
                <th className="num">ปกติ</th>
                <th className="num">ทำงานบางส่วน</th>
                <th className="num">ล่ม</th>
                <th className="num">ไม่ทราบ</th>
                <th className="num">% ปกติ</th>
              </tr>
            </thead>
            <tbody>
              {data.availability.units.map((u) => (
                <tr key={u.unit_id}>
                  <td>{u.name}</td>
                  <td className="num mono">{fmt(u.samples)}</td>
                  <td className="num mono">{fmt(u.online)}</td>
                  <td className="num mono">{fmt(u.degraded)}</td>
                  <td className="num mono">{fmt(u.down)}</td>
                  <td className="num mono">{fmt(u.unknown)}</td>
                  <td className={`num mono${u.ok_pct !== null && u.ok_pct < 99 ? " bad" : ""}`}>
                    {pctText(u.ok_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section no="04" title="ภาพรวมการเข้าสู่ระบบ" en="Authentication Overview" flush>
        <dl className="cx-report-facts">
          <div>
            <dt>อัตราเข้าสู่ระบบสำเร็จ</dt>
            <dd className="mono">{pctText(data.logins.success_rate)}</dd>
          </div>
          <div>
            <dt>อนุญาตทันที</dt>
            <dd className="mono">{fmt(data.logins.allowed)}</dd>
          </div>
          <div>
            <dt>คะแนนความเสี่ยงเฉลี่ย</dt>
            <dd className="mono">{data.risk.avg === null ? "—" : data.risk.avg.toFixed(3)}</dd>
          </div>
          <div>
            <dt>จาก IP ที่อยู่ในรายการโจมตี</dt>
            <dd className="mono">{fmt(data.risk.attack_ip)}</dd>
          </div>
          <div>
            <dt>ผู้ใช้ใหม่</dt>
            <dd className="mono">{fmt(data.users.new)}</dd>
          </div>
          <div>
            <dt>เหตุการณ์ใน Audit Log</dt>
            <dd className="mono">{fmt(data.audit.events)}</dd>
          </div>
        </dl>

        <div className="cx-rep-chart-head">
          <h4 className="cx-rep-sub">ปริมาณการเข้าสู่ระบบรายวัน</h4>
          <div className="cx-report-legend mono">
            <span>
              <i className="allow" /> อนุญาต
            </span>
            <span>
              <i className="challenge" /> ยืนยันเพิ่ม
            </span>
            <span>
              <i className="block" /> ระงับ
            </span>
          </div>
        </div>
        <div className="cx-report-chart">
          <div className="bars">
            {data.daily.map((d) => {
              const allow = Math.max(d.total - d.challenged - d.blocked, 0);
              const h = (v: number) => `${(v / maxDay) * 100}%`;
              return (
                <div
                  key={d.date}
                  className="bar"
                  title={`${d.date} — ${d.total} ครั้ง (ยืนยันเพิ่ม ${d.challenged} · ระงับ ${d.blocked})`}
                >
                  {d.total > 0 ? (
                    <>
                      <i className="block" style={{ height: h(d.blocked) }} />
                      <i className="challenge" style={{ height: h(d.challenged) }} />
                      <i className="allow" style={{ height: h(allow) }} />
                    </>
                  ) : (
                    <i className="empty" />
                  )}
                </div>
              );
            })}
          </div>
          <div className="axis mono">
            {data.daily.map((d, i) => (
              <span key={d.date}>{i === 0 || (i + 1) % 5 === 0 ? Number(d.date.slice(8)) : ""}</span>
            ))}
          </div>
        </div>

        <div className="cx-rep-grid2">
          <table className="cx-report-table">
            <thead>
              <tr>
                <th>วิธียืนยันตัวตน</th>
                <th className="num">ครั้ง</th>
                <th className="num">สัดส่วน</th>
              </tr>
            </thead>
            <tbody>
              {data.login_methods.length === 0 ? (
                <tr>
                  <td colSpan={3}>—</td>
                </tr>
              ) : (
                data.login_methods.map((m) => (
                  <tr key={m.method ?? "unknown"}>
                    <td>{m.method ? (METHOD_LABEL[m.method] ?? m.method) : "ไม่ระบุ"}</td>
                    <td className="num mono">{fmt(m.total)}</td>
                    <td className="num mono">{share(m.total, data.logins.total)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          <table className="cx-report-table">
            <thead>
              <tr>
                <th>ประเทศต้นทาง</th>
                <th className="num">ครั้ง</th>
                <th className="num">สัดส่วน</th>
              </tr>
            </thead>
            <tbody>
              {data.geo.length === 0 ? (
                <tr>
                  <td colSpan={3}>—</td>
                </tr>
              ) : (
                data.geo.map((g) => (
                  <tr key={g.country ?? "unknown"}>
                    <td>{countryText(g.country)}</td>
                    <td className="num mono">{fmt(g.total)}</td>
                    <td className="num mono">{share(g.total, data.logins.total)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Section>

      <Section no="05" title="เหตุการณ์ด้านความปลอดภัย" en="Security Events" flush>
        <dl className="cx-report-facts">
          <div>
            <dt>การแจ้งเตือน API ทั้งหมด</dt>
            <dd className="mono">{fmt(data.security_summary.api_alerts.total)}</dd>
          </div>
          <div>
            <dt>ระดับวิกฤต</dt>
            <dd className="mono">{fmt(data.security_summary.api_alerts.critical)}</dd>
          </div>
          <div>
            <dt>ยังไม่ปิด</dt>
            <dd className="mono">{fmt(data.security_summary.api_alerts.unresolved)}</dd>
          </div>
          <div>
            <dt>IP ที่เพิ่มใน blacklist (รวมฟีดอัตโนมัติ)</dt>
            <dd className="mono">{fmt(data.security_summary.ip_blacklist_added)}</dd>
          </div>
          <div>
            <dt>แอดมินบังคับออกจากระบบ</dt>
            <dd className="mono">{fmt(data.security_summary.force_logouts)}</dd>
          </div>
          <div>
            <dt>ระบบย่อยลงทะเบียน / อนุมัติในเดือน</dt>
            <dd className="mono">
              {fmt(data.subsystem_status.registered_in_month)} /{" "}
              {fmt(data.subsystem_status.approved_in_month)}
            </dd>
          </div>
        </dl>
        {data.security_events.length === 0 ? (
          <p className="cx-rep-empty">ไม่มีเหตุการณ์ด้านความปลอดภัยที่บันทึกไว้ในเดือนนี้</p>
        ) : (
          <table className="cx-report-table">
            <thead>
              <tr>
                <th>วันที่</th>
                <th>เหตุการณ์</th>
                <th>แหล่งข้อมูล</th>
                <th className="num">จำนวน</th>
                <th className="num">ระดับ</th>
              </tr>
            </thead>
            <tbody>
              {data.security_events.map((e) => (
                <tr key={`${e.date}-${e.source}-${e.code}-${e.severity}`}>
                  <td className="mono nowrap">{dayText(e.date)}</td>
                  <td>{e.label}</td>
                  <td>{e.source === "api_alert" ? "API Guard" : "Audit log"}</td>
                  <td className="num mono">{fmt(e.count)}</td>
                  <td className="num">
                    <Tag tone={e.severity}>{LEVEL_LABEL[e.severity]}</Tag>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section no="06" title="ข้อเสนอแนะ" en="Recommendations" flush>
        {recs.length === 0 ? (
          <p className="cx-rep-empty">ไม่มีข้อเสนอแนะจากข้อมูลเดือนนี้</p>
        ) : (
          <table className="cx-report-table cx-rep-recs">
            <thead>
              <tr>
                <th className="idx">#</th>
                <th>ข้อเสนอแนะ</th>
                <th>เหตุผล</th>
                <th className="num">ความสำคัญ</th>
                <th className="no-print" aria-label="จัดการ" />
              </tr>
            </thead>
            <tbody>
              {recs.map((r, i) => (
                <tr key={r.id}>
                  <td className="idx mono">{i + 1}</td>
                  <td className="wrap">
                    <Editable text={r.text} placeholder="พิมพ์ข้อเสนอแนะ" />
                  </td>
                  <td className="wrap muted">
                    <Editable text={r.reason} placeholder="พิมพ์เหตุผล" />
                  </td>
                  <td className="num">
                    <button
                      type="button"
                      className="cx-rep-priority"
                      title="กดเพื่อเปลี่ยนความสำคัญ"
                      onClick={() =>
                        setRecs((rows) =>
                          rows.map((x) =>
                            x.id === r.id ? { ...x, priority: PRIORITY_NEXT[x.priority] } : x
                          )
                        )
                      }
                    >
                      <Tag tone={PRIORITY_TONE[r.priority]}>{PRIORITY_LABEL[r.priority]}</Tag>
                    </button>
                  </td>
                  <td className="no-print">
                    <button
                      type="button"
                      className="cx-rep-mini"
                      onClick={() => setRecs((rows) => rows.filter((x) => x.id !== r.id))}
                    >
                      ลบ
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="cx-rep-actions no-print">
          <button
            type="button"
            className="cx-rep-mini"
            onClick={() =>
              setRecs((rows) => [
                ...rows,
                { id: `manual-${Date.now()}`, priority: "medium", code: "manual", text: "", reason: "" },
              ])
            }
          >
            เพิ่มข้อเสนอแนะ
          </button>
        </div>
      </Section>

      <Section no="07" title="แนวโน้ม 6 เดือนย้อนหลัง" en="6-Month Trend" flush>
        <table className="cx-report-table">
          <thead>
            <tr>
              <th>เดือน</th>
              <th className="num">เข้าสู่ระบบ</th>
              <th className="num">ผู้ใช้</th>
              <th className="num">ระงับ</th>
              <th className="num">อัตราระงับ</th>
              <th className="num">ยืนยันเพิ่ม</th>
              <th className="num">เหตุการณ์ผิดปกติ</th>
            </tr>
          </thead>
          <tbody>
            {data.trend.map((t) => (
              <tr key={t.month} className={t.month === data.month ? "current" : undefined}>
                <td>{thaiMonth(t.month)}</td>
                <td className="num mono">{fmt(t.logins)}</td>
                <td className="num mono">{fmt(t.unique_users)}</td>
                <td className="num mono">{fmt(t.blocked)}</td>
                <td className="num mono">{pctText(t.block_rate)}</td>
                <td className="num mono">{fmt(t.challenged)}</td>
                <td className="num mono">{fmt(t.incidents)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section no="08" title="บทสรุป" en="Conclusion">
        <Editable text={data.narrative.conclusion} />
      </Section>

      <Section no="ก" title="ภาคผนวก: ประสิทธิภาพ API" en="Appendix — API Performance" flush>
        {data.api_performance.length === 0 ? (
          <p className="cx-rep-empty">ไม่มี request ที่บันทึกไว้ในเดือนนี้</p>
        ) : (
          <table className="cx-report-table">
            <thead>
              <tr>
                <th>กลุ่ม endpoint</th>
                <th className="num">Requests</th>
                <th className="num">เฉลี่ย</th>
                <th className="num">P95</th>
                <th className="num">P99</th>
                <th className="num">5xx</th>
                <th className="num">อัตรา 5xx</th>
              </tr>
            </thead>
            <tbody>
              {data.api_performance.map((g) => (
                <tr key={g.group}>
                  <td>{g.label}</td>
                  <td className="num mono">{fmt(g.requests)}</td>
                  <td className="num mono">{msText(g.avg_ms)}</td>
                  <td className="num mono">{msText(g.p95_ms)}</td>
                  <td className="num mono">{msText(g.p99_ms)}</td>
                  <td className="num mono">{fmt(g.server_errors)}</td>
                  <td className="num mono">{pctText(g.error_rate)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td>รวมทุก endpoint</td>
                <td className="num mono">{fmt(data.api_overall.requests)}</td>
                <td className="num mono">{msText(data.api_overall.avg_ms)}</td>
                <td className="num mono">{msText(data.api_overall.p95_ms)}</td>
                <td className="num mono">{msText(data.api_overall.p99_ms)}</td>
                <td className="num mono">{fmt(data.api_overall.server_errors)}</td>
                <td className="num mono">{pctText(data.api_overall.error_rate)}</td>
              </tr>
            </tfoot>
          </table>
        )}
        <h4 className="cx-rep-sub pad">การตรวจยืนยันผลของโมเดล (ML feedback)</h4>
        <dl className="cx-report-facts">
          <div>
            <dt>รายการที่ตรวจยืนยันแล้ว</dt>
            <dd className="mono">{fmt(data.ml_feedback.labeled)}</dd>
          </div>
          <div>
            <dt>False / True positive</dt>
            <dd className="mono">
              {fmt(data.ml_feedback.false_positive)} / {fmt(data.ml_feedback.true_positive)}
            </dd>
          </div>
          <div>
            <dt>อัตรา false positive</dt>
            <dd className="mono">
              {data.ml_feedback.fp_rate === null
                ? `ยังคำนวณไม่ได้ (${data.ml_feedback.labeled}/${data.ml_feedback.min_labels})`
                : `${data.ml_feedback.fp_rate}%`}
            </dd>
          </div>
        </dl>
      </Section>

      <Section no="ข" title="ภาคผนวก: ข้อจำกัดของข้อมูล" en="Appendix — Data Limitations">
        <ul className="cx-rep-limits">
          {data.unavailable.map((u) => (
            <li key={u}>{UNAVAILABLE_TEXT[u] ?? u}</li>
          ))}
          <li>จำนวนระบบย่อยที่ใช้งาน / รออนุมัติ เป็นค่า ณ เวลาที่สร้างรายงาน ไม่ใช่ค่า ณ สิ้นเดือน</li>
          <li>
            ประเทศต้นทางอ่านจาก IP สาธารณะเท่านั้น การเข้าสู่ระบบจาก IP ภายในจะแสดงเป็น
            &ldquo;ไม่ทราบ&rdquo;
          </li>
        </ul>
      </Section>

      <p className="cx-rep-footer">
        รายงานนี้สร้างจากข้อมูลในระบบ Central Auth Hub · สรุปผู้บริหาร ข้อเสนอแนะ และบทสรุป
        ร่างโดยระบบจากตัวเลขในรายงานและผ่านการแก้ไขโดยผู้จัดทำ
      </p>
    </>
  );
}
