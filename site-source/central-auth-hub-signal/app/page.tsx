"use client";

import { useState } from "react";
import { Switch } from "@/components/ui/switch";
import {
  Activity, Bell, Boxes, BrainCircuit, ChevronDown, CircleCheck,
  Clock3, Command, FileClock, Fingerprint, Gauge, KeyRound,
  LayoutDashboard, LockKeyhole, LogOut, MoreHorizontal, Network,
  RefreshCw, Search, Settings, ShieldAlert, ShieldCheck, Terminal,
  UserRound, Users, Waypoints, Zap, Wifi, TriangleAlert,
  Globe2, ChartNoAxesCombined,
} from "lucide-react";

const liveEvents = [
  { email: "narin.s@pnu.ac.th", system: "Student Portal", ip: "192.168.10.24", score: 0.12, decision: "ALLOW", tone: "low", time: "14:32:08" },
  { email: "fura.f@pnu.ac.th", system: "Library", ip: "192.168.10.86", score: 0.48, decision: "MFA", tone: "mid", time: "14:31:54" },
  { email: "staff.it@pnu.ac.th", system: "HR Connect", ip: "10.42.1.17", score: 0.08, decision: "ALLOW", tone: "low", time: "14:31:41" },
  { email: "unknown@external", system: "Research DB", ip: "185.17.22.91", score: 0.91, decision: "BLOCK", tone: "crit", time: "14:30:19" },
];

const hourlyAuth = [
  { hour: "00", allow: 32, mfa: 4, block: 1 }, { hour: "02", allow: 22, mfa: 3, block: 0 },
  { hour: "04", allow: 14, mfa: 2, block: 1 }, { hour: "06", allow: 39, mfa: 5, block: 0 },
  { hour: "08", allow: 76, mfa: 10, block: 2 }, { hour: "10", allow: 91, mfa: 13, block: 3 },
  { hour: "12", allow: 73, mfa: 8, block: 2 }, { hour: "14", allow: 96, mfa: 14, block: 4 },
  { hour: "16", allow: 83, mfa: 11, block: 2 }, { hour: "18", allow: 62, mfa: 8, block: 1 },
  { hour: "20", allow: 51, mfa: 6, block: 2 }, { hour: "22", allow: 38, mfa: 5, block: 1 },
];

const riskBuckets = [18, 29, 41, 58, 72, 82, 76, 61, 43, 29, 19, 13, 9, 7, 5, 4, 3, 2, 1, 1];

function AuthVolumeChart() {
  return <div className="volume-chart" role="img" aria-label="ปริมาณการยืนยันตัวตนรายชั่วโมง แยก Allow MFA และ Block">
    <div className="chart-y"><span>100</span><span>75</span><span>50</span><span>25</span><span>0</span></div>
    <div className="bar-plot">{hourlyAuth.map((item) => <div className="hour-column" key={item.hour}>
      <div className="stacked-bar" title={`${item.hour}:00 · Allow ${item.allow} · MFA ${item.mfa} · Block ${item.block}`}>
        <i className="bar-block" style={{ height: `${item.block}%` }} /><i className="bar-mfa" style={{ height: `${item.mfa}%` }} /><i className="bar-allow" style={{ height: `${item.allow}%` }} />
      </div><span className="mono">{item.hour}</span>
    </div>)}</div>
  </div>;
}

function RiskDistribution() {
  return <div className="risk-distribution" role="img" aria-label="การกระจายคะแนนความเสี่ยง พร้อมเส้น MFA 0.60 และ Block 0.85">
    <div className="histogram">{riskBuckets.map((height, index) => <i key={index} className={index >= 17 ? "crit" : index >= 12 ? "high" : index >= 6 ? "mid" : "low"} style={{ height: `${height}%` }} />)}
      <span className="threshold mfa-line"><b className="mono">MFA · 0.60</b></span><span className="threshold block-line"><b className="mono">BLOCK · 0.85</b></span>
    </div><div className="histogram-axis mono"><span>0.00</span><span>0.25</span><span>0.50</span><span>0.75</span><span>1.00</span></div>
  </div>;
}

function Signal({ tone = "live" }: { tone?: "live" | "warn" | "danger" }) {
  return <span className={`signal-dot ${tone}`} aria-hidden="true"><i /></span>;
}

function RiskMeter({ value, tone }: { value: number; tone: string }) {
  return <div className="risk-cell"><div className="risk-track"><i className={tone} style={{ width: `${value * 100}%` }} /></div><b className="mono">{value.toFixed(2)}</b></div>;
}

export default function Home() {
  const [google, setGoogle] = useState(true);
  const [passkey, setPasskey] = useState(true);
  const [refreshed, setRefreshed] = useState(false);

  const refresh = () => { setRefreshed(true); window.setTimeout(() => setRefreshed(false), 900); };

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand-lockup"><div className="brand-icon"><Command size={19} /><Signal /></div><div><strong>HUB</strong><span>SECURITY CONTROL</span></div></div>
        <div className="environment"><Signal /><span>PRODUCTION</span><b className="mono">TH-SOUTH-01</b></div>

        <nav aria-label="เมนูหลัก">
          <p className="nav-group">COMMAND</p>
          <a className="nav-link active" href="/dashboard"><LayoutDashboard />ภาพรวมระบบ</a>
          <a className="nav-link" href="/activity"><Activity />การเข้าใช้งาน<span className="nav-live">LIVE</span></a>
          <a className="nav-link" href="/users"><Users />ผู้ใช้งาน</a>
          <a className="nav-link" href="/subsystems"><Boxes />ระบบย่อย</a>
          <p className="nav-group divided">SECURITY</p>
          <a className="nav-link" href="/ml"><BrainCircuit />ML / ความผิดปกติ</a>
          <a className="nav-link" href="/api-alerts"><ShieldAlert />API Alerts</a>
          <a className="nav-link" href="/ip-blacklist"><Network />IP Blacklist</a>
          <a className="nav-link" href="/audit"><FileClock />Audit Log</a>
          <a className="nav-link" href="/notifications"><Bell />แจ้งเตือน</a>
          <p className="nav-group divided">DEVELOPER</p>
          <a className="nav-link" href="/developer/subsystems"><Terminal />Developer Portal</a>
          <a className="nav-link" href="/pending-requests"><Waypoints />คำขออนุมัติ</a>
          <a className="nav-link" href="/account"><UserRound />บัญชีของฉัน</a>
        </nav>

        <div className="sidebar-foot">
          <div className="operator"><div className="avatar">FF</div><div><strong>Fura Fae</strong><span>Super Admin</span></div><MoreHorizontal size={17} /></div>
          <button className="logout"><LogOut size={15} />ออกจากระบบ</button>
        </div>
      </aside>

      <section className="stage">
        <header className="topbar">
          <div className="crumb"><span className="mono">HUB</span><i>/</i><strong>ภาพรวมระบบ</strong></div>
          <label className="search"><Search size={16} /><input aria-label="ค้นหา" placeholder="ค้นหาผู้ใช้, client ID, IP..."/><kbd className="mono">⌘ K</kbd></label>
          <a className="top-icon" href="/notifications" aria-label="เปิดหน้าแจ้งเตือน"><Bell size={18}/></a>
          <div className="time mono"><Clock3 size={14}/><span>14:32:18 ICT</span></div>
        </header>

        <section className="command-bar">
          <div className="command-copy"><div className="live-label"><Signal /> LIVE CONTROL SURFACE</div><h1>ภาพรวมระบบ</h1></div>
          <div className="command-actions">
            <div className="health-stamp"><ShieldCheck size={17}/><div><span>SYSTEM STATUS</span><strong>ทุกระบบทำงานปกติ</strong></div></div>
            <button className={`refresh ${refreshed ? "spin" : ""}`} onClick={refresh}><RefreshCw size={16}/>{refreshed ? "อัปเดตแล้ว" : "ตรวจสุขภาพ"}</button>
          </div>
          <div className="signal-rule" />
        </section>

        <div className="document" id="overview">
          <section className="attention-banner">
            <div className="attention-icon"><Zap size={18}/><Signal tone="warn" /></div>
            <div><span className="overline">ACTION REQUIRED</span><strong>มี 5 รายการที่รอการตรวจสอบ</strong><p>2 subsystem approvals · 3 developer change requests</p></div>
            <button>เปิดรายการงาน <span>→</span></button>
          </section>

          <section className="kpi-grid" aria-label="สรุปสถานะระบบ">
            <article className="kpi signal-kpi"><div className="kpi-head"><span>USERS TOTAL</span><Users size={16}/></div><strong className="mono">1,284</strong><p><b>+24</b> ใน 30 วันที่ผ่านมา</p></article>
            <article className="kpi"><div className="kpi-head"><span>SUBSYSTEMS</span><Boxes size={16}/></div><strong className="mono">12</strong><p><Signal /> <b>10 active</b> · 2 pending</p></article>
            <article className="kpi"><div className="kpi-head"><span>LOGINS · 24H</span><Fingerprint size={16}/></div><strong className="mono">3,842</strong><p><b>98.7%</b> สำเร็จ</p></article>
            <article className="kpi risk-kpi"><div className="kpi-head"><span>HIGH RISK</span><ShieldAlert size={16}/></div><strong className="mono">17</strong><p><b>4 blocked</b> · 13 challenged</p></article>
            <article className="kpi"><div className="kpi-head"><span>AVG. RISK</span><Gauge size={16}/></div><strong className="mono">0.18</strong><p>ต่ำกว่าเมื่อวาน <b>0.03</b></p></article>
          </section>

          <section className="security-overview-grid">
            <article className="card auth-volume-card">
              <div className="card-head chart-card-head"><div><span className="overline">AUTHENTICATION TRAFFIC</span><h2>ปริมาณการยืนยันตัวตน · 24 ชั่วโมง</h2><p>แยกผลลัพธ์ Allow, MFA และ Block รายชั่วโมง</p></div><div className="chart-legend"><span><i className="allow"/>Allow</span><span><i className="mfa"/>MFA</span><span><i className="block"/>Block</span></div></div>
              <AuthVolumeChart />
              <div className="chart-summary"><div><span>ช่วงสูงสุด</span><b className="mono">14:00–16:00</b></div><div><span>เทียบเมื่อวาน</span><b className="positive mono">+8.4%</b></div><div><span>Blocked peak</span><b className="danger-text mono">4 events</b></div></div>
            </article>

            <article className="card subsystem-card" id="systems">
              <div className="subsystem-head"><div><span className="overline">SERVICE HEALTH MATRIX</span><h2>การเชื่อมต่อระบบย่อย</h2><p>สถานะ endpoint และ response time ล่าสุด</p></div><div className="matrix-health"><Signal/><span><b className="mono">2 / 2</b> healthy</span></div></div>
              <div className="matrix-labels mono"><span>SERVICE</span><span>UPTIME · 30D</span><span>LATENCY</span></div>
              <div className="service-matrix">
                <div className="service-row">
                  <div className="service-index mono"><span>01</span><i/></div>
                  <div className="service-name"><strong>ระบบห้องสมุด</strong><span className="mono">Library Office</span></div>
                  <div className="uptime-value"><b className="mono">99.99%</b><span>operational</span></div>
                  <div className="latency-value"><b className="mono">351 <small>ms</small></b><span className="latency-state fast">normal</span></div>
                  <svg className="latency-spark fast" viewBox="0 0 70 22" aria-label="แนวโน้ม latency ระบบห้องสมุด"><path d="M1 15 L9 14 L17 16 L25 11 L33 13 L41 9 L49 10 L57 6 L69 8"/></svg>
                </div>
                <div className="service-row">
                  <div className="service-index mono"><span>02</span><i/></div>
                  <div className="service-name"><strong>ระบบหอพัก</strong><span className="mono">Dormitory</span></div>
                  <div className="uptime-value"><b className="mono">99.94%</b><span>operational</span></div>
                  <div className="latency-value"><b className="mono">641 <small>ms</small></b><span className="latency-state watch">watch</span></div>
                  <svg className="latency-spark watch" viewBox="0 0 70 22" aria-label="แนวโน้ม latency ระบบหอพัก"><path d="M1 16 L9 13 L17 15 L25 8 L33 12 L41 6 L49 9 L57 5 L69 3"/></svg>
                </div>
              </div>
              <div className="subsystem-foot"><span><Wifi size={13}/>ตรวจทุก <b className="mono">30s</b></span><span>Median <b className="mono">496ms</b></span><code className="mono">14:32:08 ICT</code></div>
            </article>
          </section>

          <section className="main-grid">
            <article className="card activity-card" id="activity">
              <div className="card-head"><div><div className="title-row"><Signal/><h2>การเข้าใช้งานล่าสุด</h2><span className="live-chip mono">LIVE</span></div><p>เหตุการณ์ยืนยันตัวตนจากทุกระบบย่อย</p></div><button className="link-button">ดู Realtime ทั้งหมด <span>→</span></button></div>
              <div className="table-wrap"><table><thead><tr><th>เวลา</th><th>ผู้ใช้งาน</th><th>ระบบ</th><th>IP ADDRESS</th><th>RISK SCORE</th><th>DECISION</th></tr></thead><tbody>{liveEvents.map((event) => <tr key={event.time}><td className="mono time-cell">{event.time}</td><td className="mono email-cell">{event.email}</td><td>{event.system}</td><td><span className="data-chip mono">{event.ip}</span></td><td><RiskMeter value={event.score} tone={event.tone}/></td><td><span className={`decision ${event.tone}`}><i/>{event.decision}</span></td></tr>)}</tbody></table></div>
              <div className="feed-foot"><Signal/><span>เชื่อมต่อ realtime channel แล้ว</span><b className="mono">latency 28ms</b></div>
            </article>

            <article className="card risk-card" id="ml">
              <div className="card-head"><div><span className="overline">4-LAYER RISK ENGINE</span><h2>การตัดสินใจ · 24 ชั่วโมง</h2></div><button className="icon-more" aria-label="เมนู"><MoreHorizontal size={18}/></button></div>
              <div className="donut-row"><div className="donut"><div><strong className="mono">3,842</strong><span>sessions</span></div></div><div className="donut-legend"><p><i className="allow"/><span>Allow</span><b className="mono">3,596</b><em>93.6%</em></p><p><i className="mfa"/><span>MFA</span><b className="mono">201</b><em>5.2%</em></p><p><i className="block"/><span>Block</span><b className="mono">45</b><em>1.2%</em></p></div></div>
              <div className="engine-status"><div><BrainCircuit size={17}/><span>Model runtime</span></div><b><Signal/>ONLINE</b><code className="mono">v0.3.0 · p95 18ms</code></div>
            </article>
          </section>

          <section className="analytics-grid">
            <article className="card distribution-card">
              <div className="card-head chart-card-head"><div><span className="overline">RISK DISTRIBUTION</span><h2>การกระจายคะแนนความเสี่ยง</h2><p>Session ทั้งหมดใน 24 ชั่วโมง · เส้นประคือนโยบายปัจจุบัน</p></div><ChartNoAxesCombined size={18}/></div>
              <RiskDistribution />
              <div className="risk-bands"><span><i className="low"/>Low <b className="mono">3,154</b></span><span><i className="mid"/>Medium <b className="mono">487</b></span><span><i className="high"/>High <b className="mono">156</b></span><span><i className="crit"/>Critical <b className="mono">45</b></span></div>
            </article>

            <article className="card threat-card">
              <div className="card-head"><div><span className="overline">SECURITY SIGNALS</span><h2>สัญญาณความผิดปกติที่พบ</h2><p>จัดกลุ่มจาก API Alerts และ Risk Engine</p></div><TriangleAlert size={18}/></div>
              <div className="threat-bars">
                <div><p><span>อุปกรณ์ใหม่ผิดเวลา</span><b className="mono">38</b></p><i><span style={{width:"86%"}}/></i></div>
                <div><p><span>Failed login burst</span><b className="mono">27</b></p><i><span style={{width:"64%"}}/></i></div>
                <div><p><span>Geo / ASN เปลี่ยนฉับพลัน</span><b className="mono">16</b></p><i><span style={{width:"43%"}}/></i></div>
                <div><p><span>API probing pattern</span><b className="mono">9</b></p><i><span className="critical" style={{width:"26%"}}/></i></div>
              </div>
              <div className="source-strip"><Globe2 size={15}/><div><span>แหล่งที่มีความเสี่ยงสูงสุด</span><b>External network</b></div><code className="mono">42.7%</code></div>
            </article>
          </section>

          <section className="lower-grid">
            <article className="card auth-card">
              <div className="card-head"><div><span className="overline">AUTH POLICY</span><h2>วิธีการเข้าสู่ระบบ</h2><p>นโยบายส่วนกลางสำหรับ Admin Console</p></div><LockKeyhole size={19}/></div>
              <div className="auth-method"><div className="method-icon passkey"><KeyRound size={18}/></div><div><strong>Passkey</strong><span>WebAuthn · phishing-resistant</span></div><span className="recommended">แนะนำ</span><Switch checked={passkey} onCheckedChange={setPasskey} aria-label="เปิดใช้งาน Passkey" className="data-[state=checked]:bg-[#13b89a]"/></div>
              <div className="auth-method"><div className="method-icon google">G</div><div><strong>Google Workspace</strong><span>OAuth 2.0 · @pnu.ac.th only</span></div><Switch checked={google} onCheckedChange={setGoogle} aria-label="เปิดใช้งาน Google Workspace" className="data-[state=checked]:bg-[#13b89a]"/></div>
              <div className="stepup"><div><ShieldCheck size={16}/><span>Step-up verification</span></div><strong className="mono">TRUST WINDOW · 15 MIN</strong></div>
            </article>

            <article className="card queue-card">
              <div className="card-head"><div><span className="overline">PENDING QUEUE</span><h2>งานที่รอการตัดสินใจ</h2></div><span className="queue-total mono">05</span></div>
              <div className="queue-item"><div className="queue-icon"><Waypoints size={17}/></div><div><strong>Subsystem approval</strong><span>Research Data Platform</span><code className="mono">client_req_09fd</code></div><time className="mono">12 min</time><ChevronDown size={16}/></div>
              <div className="queue-item"><div className="queue-icon violet"><Settings size={17}/></div><div><strong>Change request</strong><span>Library · เพิ่ม redirect URI</span><code className="mono">req_7b31</code></div><time className="mono">38 min</time><ChevronDown size={16}/></div>
              <div className="queue-item"><div className="queue-icon"><UserRound size={17}/></div><div><strong>Owner transfer</strong><span>Classroom Security System</span><code className="mono">req_419c</code></div><time className="mono">1 hr</time><ChevronDown size={16}/></div>
              <button className="queue-all">ดูคำขอทั้งหมด <span>→</span></button>
            </article>
          </section>

          <footer><span>Central Auth Hub</span><span className="mono">build 2026.08.27 · audit chain verified</span><span><CircleCheck size={13}/> All services operational</span></footer>
        </div>
      </section>
    </main>
  );
}
