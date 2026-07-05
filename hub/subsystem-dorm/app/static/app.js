/** @jsxRuntime classic */
/* บังคับ JSX → React.createElement (ใช้ global React) — กัน Babel automatic runtime
   ที่ inject `import {jsx} from "react/jsx-runtime"` ทำให้ classic script พัง
   ("Cannot use import statement outside a module") */
/* ============================================================
   ระบบหอพักนักศึกษา — React SPA
   Theme B · Hostel Pop (Bauhaus) · Sidebar layout
   Roles: student · teacher · staff
   ============================================================ */
const { useState, useEffect, useCallback, useRef } = React;

// ─── API helpers ──────────────────────────────────────────────
const api = {
  get: async (url) => {
    const r = await fetch(url, { credentials: "include" });
    if (r.status === 401) { window.location.href = "/login"; throw new Error("Unauth"); }
    if (!r.ok) throw new Error(`API error ${r.status}`);
    return r.json();
  },
};

// ─── Hash router ──────────────────────────────────────────────
const getHash = () => {
  const h = window.location.hash.slice(1); // remove #
  const [page, param] = h.split("/");
  return { page: page || "home", param: param || null };
};

// ─── SVG Icons ────────────────────────────────────────────────
const I = {
  home: <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/></svg>,
  bed: <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M3 10V6a1 1 0 011-1h16a1 1 0 011 1v4M3 10v8m18-8v8M3 18h18"/></svg>,
  user: <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>,
  users: <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/></svg>,
  doc: <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/></svg>,
  logout: <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/></svg>,
  chart: <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>,
  arrow: <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M14 5l7 7m0 0l-7 7m7-7H3"/></svg>,
  check: <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="3"><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7"/></svg>,
  x: <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="3"><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>,
  spin: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{animation:"spin .8s linear infinite"}}><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>,
  search: <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5"><circle cx="11" cy="11" r="7"/><path strokeLinecap="round" d="M20 20l-3-3"/></svg>,
  bell: <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.4-1.4A2 2 0 0118 14.17V11a6 6 0 10-12 0v3.17a2 2 0 01-.6 1.43L4 17h5m6 0a3 3 0 11-6 0"/></svg>,
  plus: <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5"><path strokeLinecap="round" d="M12 5v14M5 12h14"/></svg>,
  sparkle: <svg width="16" height="16" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2l2.4 6.6L21 11l-6.6 2.4L12 20l-2.4-6.6L3 11l6.6-2.4L12 2z"/></svg>,
  clock: <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5"><circle cx="12" cy="12" r="9"/><path strokeLinecap="round" d="M12 7v5l3 2"/></svg>,
};

// ─── Shared components ─────────────────────────────────────────

const Loading = () => (
  <div className="loading-state">{I.spin} กำลังโหลด...</div>
);

const StatusBadge = ({ status }) => {
  const map = {
    pending: "⏳ รออนุมัติ", approved: "✅ อนุมัติแล้ว",
    checked_in: "🏠 check-in", rejected: "❌ ปฏิเสธ",
    cancelled: "🚫 ยกเลิก", active: "✅ active",
    available: "✅ ว่าง", full: "🔴 เต็ม", maintenance: "🔧 ซ่อม",
    staff: "👔 staff", teacher: "📚 teacher", resident: "👤 resident",
  };
  return (
    <span className={`badge badge-${status}`}>{map[status] || status}</span>
  );
};

const StatCard = ({ icon, label, value, sub, accentColor, bgTint }) => (
  <div className="card" style={{ padding: 18 }}>
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
      <span style={{ fontSize: 12, color: "var(--ink-mute)", fontWeight: 500 }}>{label}</span>
      <div style={{
        width: 32, height: 32,
        background: bgTint || "var(--bg-soft)",
        color: accentColor || "var(--ink)",
        display: "grid", placeItems: "center",
        border: "1.5px solid var(--ink)",
      }}>{icon}</div>
    </div>
    <div className="display" style={{ fontSize: 30, margin: "4px 0 2px" }}>{value}</div>
    {sub && <div style={{ fontSize: 11, color: "var(--ink-mute)" }}>{sub}</div>}
  </div>
);

// ─── SideNav ─────────────────────────────────────────────────
const SideNav = ({ user, page, setPage }) => {
  const role = user?.user_type || "student";

  const studentMenu = [
    { id: "home",  icon: I.home,  label: "ภาพรวม" },
    { id: "rooms", icon: I.bed,   label: "ห้องว่าง" },
    { id: "me",    icon: I.user,  label: "โปรไฟล์ของฉัน" },
  ];
  const teacherMenu = [
    { id: "home",      icon: I.chart, label: "ภาพรวม" },
    { id: "residents", icon: I.users, label: "รายชื่อผู้พัก" },
    { id: "rooms",     icon: I.bed,   label: "ห้องทั้งหมด" },
    { id: "me",        icon: I.user,  label: "โปรไฟล์ของฉัน" },
  ];
  const staffMenu = [
    { id: "home",         icon: I.chart, label: "ภาพรวม" },
    { id: "reservations", icon: I.doc,   label: "คำขอจอง" },
    { id: "residents",    icon: I.users, label: "ผู้พักทั้งหมด" },
    { id: "me",           icon: I.user,  label: "โปรไฟล์ของฉัน" },
  ];

  const menu = role === "staff" ? staffMenu : role === "teacher" ? teacherMenu : studentMenu;
  const sectionLabel = role === "staff" ? "เมนูเจ้าหน้าที่" : role === "teacher" ? "เมนูอาจารย์" : "เมนูนักศึกษา";

  const go = (id) => {
    setPage(id);
    window.location.hash = id;
  };

  return (
    <aside className="sidenav">
      <div className="sidenav-logo">
        <div className="sidenav-logo-sq">🏠</div>
        <span>หอพัก</span>
      </div>
      <div className="sidenav-label">{sectionLabel}</div>
      {menu.map(item => (
        <a key={item.id}
           className={`sidenav-item${page === item.id ? " active" : ""}`}
           onClick={() => go(item.id)}
           style={{ cursor: "pointer" }}>
          {item.icon}
          <span>{item.label}</span>
        </a>
      ))}
      <div className="sidenav-spacer" />

      {/* Contact admin card (Bauhaus yellow pop) */}
      <div className="sidenav-contact">
        <div className="sidenav-contact-row">
          <div className="sidenav-contact-icon">{I.users}</div>
          <div>
            <div className="sidenav-contact-title">ติดต่อผู้ดูแล</div>
            <div className="sidenav-contact-sub mono">DORM_OFFICE</div>
          </div>
        </div>
        <p className="sidenav-contact-body">
          {role === "staff" ? "ส่งต่อปัญหาให้ admin หลัก" :
           role === "teacher" ? "สอบถามข้อมูลเพิ่มเติม" :
           "แจ้งปัญหาห้อง / สัญญา / อื่นๆ"}
        </p>
        <a href={`mailto:admin@uni.ac.th?subject=สอบถามระบบหอพัก`}
           className="sidenav-contact-btn">
          ส่งอีเมล →
        </a>
      </div>

      <div className="sidenav-divider" />
      <a className="sidenav-item" href="/logout" style={{ color: "var(--bad)" }}>
        {I.logout}
        <span>ออกจากระบบ</span>
      </a>
    </aside>
  );
};

// ─── TopBar ─────────────────────────────────────────────────
const TopBar = ({ user }) => {
  const roleLabel = { staff: "STAFF", teacher: "TEACHER", student: "STUDENT", resident: "RESIDENT" };
  const subLabel = user?.student_id ? `รหัส ${user.student_id}` :
                   user?.user_type === "staff" ? "เจ้าหน้าที่หอพัก" :
                   user?.user_type === "teacher" ? "อาจารย์" : "";
  return (
    <div className="topbar">
      <div className="topbar-search">
        <span className="topbar-search-icon">{I.search}</span>
        <input className="topbar-search-input"
               placeholder="ค้นหา ห้อง · ผู้พัก · การจอง..."
               onKeyDown={e => {
                 if (e.key === "Enter") { window.location.hash = "rooms"; }
               }} />
        <span className="topbar-kbd mono">⏎</span>
      </div>
      <div className="topbar-right">
        <div className="topbar-tag mono">DORM_OS · {(roleLabel[user?.user_type] || "USER")}</div>
        <button className="topbar-bell" title="การแจ้งเตือน">
          {I.bell}
          <span className="topbar-bell-dot" />
        </button>
        <div className="topbar-divider" />
        <div className="topbar-user">
          <div className="topbar-avatar">
            {(user?.full_name || "?")[0].toUpperCase()}
          </div>
          <div>
            <div className="topbar-name">{user?.full_name}</div>
            <div className="topbar-sub mono">{subLabel || user?.email}</div>
          </div>
        </div>
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════
// HOME PAGE
// ═══════════════════════════════════════════════════════════════
const HomePage = ({ user, setPage }) => {
  const [data, setData] = useState(null);

  useEffect(() => { api.get("/api/home").then(setData).catch(console.error); }, []);

  if (!data) return <Loading />;

  const role = user?.user_type || "student";
  const stats = data.stats || {};

  const studentCards = [
    { icon: I.bed,   label: "ห้องปัจจุบัน",    value: data.current_room?.room_number || "—",
      sub: data.current_room ? `ตึก ${data.current_room.building} ชั้น ${data.current_room.floor}` : "ยังไม่ได้ check-in",
      accentColor: "var(--primary)", bgTint: "color-mix(in oklab, var(--primary) 12%, white)" },
    { icon: I.doc,   label: "สถานะการจอง",   value: data.latest_reservation?.status || "ไม่มี",
      sub: data.latest_reservation ? `สร้างเมื่อ ${data.latest_reservation.created_at?.slice(0,10)}` : "ยังไม่เคยจอง",
      accentColor: "#A8730C", bgTint: "var(--warn-bg)" },
    { icon: I.home,  label: "ห้องว่างในระบบ",  value: stats.available_rooms ?? "—",
      sub: `จาก ${stats.total_rooms ?? "—"} ห้องทั้งหมด`,
      accentColor: "var(--good)", bgTint: "var(--good-bg)" },
    { icon: I.users, label: "ผู้พักในระบบ",    value: stats.total_residents ?? "—",
      sub: `check-in แล้ว ${stats.checked_in_residents ?? 0} คน`,
      accentColor: "var(--ink)", bgTint: "var(--bg-soft)" },
  ];

  const teacherCards = [
    { icon: I.bed,   label: "ห้องทั้งหมด",      value: stats.total_rooms ?? "—",    sub: "ห้องในระบบ",
      accentColor: "var(--primary)", bgTint: "color-mix(in oklab, var(--primary) 12%, white)" },
    { icon: I.home,  label: "ห้องว่าง",          value: stats.available_rooms ?? "—", sub: "พร้อมให้จอง",
      accentColor: "var(--good)", bgTint: "var(--good-bg)" },
    { icon: I.users, label: "ผู้พักทั้งหมด",    value: stats.total_residents ?? "—", sub: "คนในระบบ",
      accentColor: "var(--ink)", bgTint: "var(--bg-soft)" },
    { icon: I.chart, label: "check-in แล้ว",   value: stats.checked_in_residents ?? "—", sub: "จากผู้พักทั้งหมด",
      accentColor: "var(--mint)", bgTint: "color-mix(in oklab, var(--mint) 20%, white)" },
  ];

  const staffCards = [
    { icon: I.doc,   label: "รอดำเนินการ",      value: stats.pending_count ?? "—",   sub: "คำขอรออนุมัติ",
      accentColor: "#A8730C", bgTint: "var(--warn-bg)" },
    { icon: I.users, label: "ผู้พักทั้งหมด",    value: stats.total_residents ?? "—", sub: "คนในระบบ",
      accentColor: "var(--primary)", bgTint: "color-mix(in oklab, var(--primary) 12%, white)" },
    { icon: I.bed,   label: "ห้องเข้าพักแล้ว",  value: (stats.total_rooms ?? 0) - (stats.available_rooms ?? 0),
      sub: `จาก ${stats.total_rooms ?? "—"} ห้อง`,
      accentColor: "var(--ink)", bgTint: "var(--bg-soft)" },
    { icon: I.home,  label: "ห้องว่าง",          value: stats.available_rooms ?? "—", sub: "พร้อมให้จอง",
      accentColor: "var(--good)", bgTint: "var(--good-bg)" },
  ];

  const cards = role === "staff" ? staffCards : role === "teacher" ? teacherCards : studentCards;
  const greeting = role === "staff" ? `มี ${stats.pending_count || 0} คำขอรออนุมัติ` :
                   role === "teacher" ? "ข้อมูลภาพรวมระบบหอพัก — อ่านอย่างเดียว" :
                   data.current_room ? `ห้อง ${data.current_room.room_number} · ตึก ${data.current_room.building}` : "ยินดีต้อนรับสู่ระบบหอพัก";

  return (
    <div className="fade-up">
      {/* Welcome banner */}
      <div style={{
        padding: "24px 28px", marginBottom: 24,
        background: "var(--ink)", color: "var(--bg-card)",
        border: "2px solid var(--line)", borderRadius: "var(--radius)",
        position: "relative", overflow: "hidden",
      }}>
        <div style={{ position: "absolute", right: 28, top: -20, width: 120, height: 120,
                      borderRadius: "50%", background: "var(--yellow)", opacity: .85 }} />
        <div style={{ position: "absolute", right: 180, top: 40, width: 50, height: 50,
                      borderRadius: "50%", background: "var(--pink)" }} />
        <div style={{ position: "relative", zIndex: 1 }}>
          <div style={{ fontSize: 12, opacity: .7, marginBottom: 6, fontFamily: "JetBrains Mono, monospace", letterSpacing: ".06em" }}>
            {role === "staff" ? "👔 STAFF_VIEW" : role === "teacher" ? "📚 TEACHER_VIEW" : "🎓 STUDENT_VIEW"}
          </div>
          <h2 className="display" style={{ fontSize: 34, margin: "0 0 8px", color: "var(--bg-card)" }}>
            สวัสดี, {user?.full_name}
          </h2>
          <p style={{ fontSize: 14, opacity: .85, margin: 0, lineHeight: 1.6 }}>{greeting}</p>
        </div>
      </div>

      {/* Stat cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 24 }}>
        {cards.map((c, i) => (
          <StatCard key={i} icon={c.icon} label={c.label} value={c.value}
                    sub={c.sub} accentColor={c.accentColor} bgTint={c.bgTint} />
        ))}
      </div>

      {/* ─── Two-column dashboard layout ─── */}
      <div className="dash-grid">
        {/* LEFT COLUMN — announcements + room/info card */}
        <div className="dash-col">
          {/* Announcements */}
          <div className="card dash-card">
            <div className="dash-card-head">
              <h3 className="dash-card-title">📣 ประกาศและกิจกรรม</h3>
              <span className="chip chip-primary">{stats.pending_count ?? 0} pending</span>
            </div>
            {(role === "staff" ? [
              [`มีคำขอจอง ${stats.pending_count ?? 0} รายการรออนุมัติ`,
               `เข้าหน้าคำขอจองเพื่อตรวจสอบและอนุมัติ`, "เร่งด่วน", "warn"],
              [`ผู้พัก ${stats.checked_in_residents ?? 0} คน check-in แล้ว`,
               `จากผู้พักทั้งหมด ${stats.total_residents ?? 0} คนในระบบ`, "อัปเดต", "primary"],
              [`ห้องว่าง ${stats.available_rooms ?? 0} ห้อง`,
               `จาก ${stats.total_rooms ?? 0} ห้องทั้งหมด — พร้อมให้จอง`, "ข้อมูล", "muted"],
            ] : role === "teacher" ? [
              [`ภาพรวมการเข้าพัก ${stats.total_rooms ? Math.round((stats.total_rooms - stats.available_rooms) / stats.total_rooms * 100) : 0}%`,
               `${stats.total_residents ?? 0} ผู้พักในระบบ — check-in แล้ว ${stats.checked_in_residents ?? 0} คน`, "สถิติ", "primary"],
              [`มีคำขอจอง ${stats.pending_count ?? 0} รายการ`,
               `รออนุมัติจากเจ้าหน้าที่หอพัก`, "ข้อมูล", "warn"],
              [`บัญชีของท่านเป็น read-only`,
               `เข้าดูข้อมูลได้ทั้งหมด — แต่ไม่สามารถจอง/อนุมัติ`, "หมายเหตุ", "muted"],
            ] : [
              data.current_room
                ? [`ห้องของคุณ: ${data.current_room.room_number}`,
                   `ตึก ${data.current_room.building} · ชั้น ${data.current_room.floor} · รองรับ ${data.current_room.capacity} คน`, "ห้องของฉัน", "primary"]
                : [`ยังไม่ได้ check-in`,
                   `เลือกห้องว่างและส่งคำขอจองได้เลย — มี ${stats.available_rooms ?? 0} ห้องพร้อมจอง`, "เริ่มต้น", "warn"],
              data.latest_reservation
                ? [`การจองล่าสุด: ${data.latest_reservation.status}`,
                   `สร้างเมื่อ ${data.latest_reservation.created_at?.slice(0,10)} — ดูประวัติได้ในโปรไฟล์`, "สถานะ", "primary"]
                : [`ยังไม่เคยจองห้อง`,
                   `เริ่มต้นจากหน้า "ห้องว่าง" เพื่อเลือกห้องที่สนใจ`, "ข้อมูล", "muted"],
              [`มีห้องว่าง ${stats.available_rooms ?? 0} ห้อง`,
               `อัปเดตล่าสุดจากระบบ — เลือกห้องที่ชอบได้`, "ข่าวสาร", "muted"],
            ]).map(([title, body, tag, kind], i) => (
              <div key={i} className={`anno-row anno-${kind}${i === 0 ? " anno-first" : ""}`}>
                <div className="anno-bar" />
                <div className="anno-body">
                  <div className="anno-row-head">
                    <div className="anno-title">{title}</div>
                    <span className="anno-tag mono">{tag}</span>
                  </div>
                  <div className="anno-text">{body}</div>
                </div>
              </div>
            ))}
          </div>

          {/* Room/info detail card (student only — replacement for bills card) */}
          {role === "student" && data.current_room && (
            <div className="card dash-card dash-room-card">
              <div className="dash-card-head">
                <h3 className="dash-card-title">🏠 ห้องของฉัน</h3>
                <span className="chip chip-good">✓ check-in</span>
              </div>
              <div className="dash-room-grid">
                <div>
                  <div className="dash-mini-label">หมายเลขห้อง</div>
                  <div className="display dash-mini-value">{data.current_room.room_number}</div>
                </div>
                <div>
                  <div className="dash-mini-label">ตึก · ชั้น</div>
                  <div className="display dash-mini-value">{data.current_room.building}-{data.current_room.floor}</div>
                </div>
                <div>
                  <div className="dash-mini-label">รองรับ</div>
                  <div className="display dash-mini-value">{data.current_room.capacity} <span style={{fontSize:14, fontWeight:500, color:"var(--ink-mute)"}}>คน</span></div>
                </div>
                <div className="dash-mini-cta">
                  <button className="btn btn-primary" onClick={() => { window.location.hash = `room/${data.current_room.id}`; }}>
                    ดูรายละเอียด →
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Staff: pending preview shortcut */}
          {role === "staff" && (
            <div className="card dash-card dash-staff-cta">
              <div className="dash-staff-cta-row">
                <div>
                  <div className="dash-mini-label">รอดำเนินการตอนนี้</div>
                  <div className="display" style={{ fontSize: 44, lineHeight: 1, marginTop: 6 }}>
                    {stats.pending_count ?? 0} <span style={{ fontSize: 16, fontWeight: 500, color: "var(--ink-mute)" }}>คำขอ</span>
                  </div>
                  <p style={{ fontSize: 13, color: "var(--ink-soft)", margin: "8px 0 0", maxWidth: 320 }}>
                    เปิดหน้าคำขอจองเพื่ออนุมัติหรือปฏิเสธ — ผู้พักจะได้รับแจ้งสถานะทันที
                  </p>
                </div>
                <button className="btn btn-primary dash-staff-cta-btn" onClick={() => setPage("reservations")}>
                  {I.doc} เปิดคำขอจอง
                </button>
              </div>
            </div>
          )}
        </div>

        {/* RIGHT COLUMN — status timeline + quick action grid */}
        <div className="dash-col">
          {/* Reservation status timeline (student) */}
          {role === "student" && data.latest_reservation && (
            <div className="card dash-card">
              <div className="dash-card-head">
                <h3 className="dash-card-title">สถานะการจองล่าสุด</h3>
                <StatusBadge status={data.latest_reservation.status} />
              </div>
              <div className="timeline-meta">
                <div className="timeline-meta-row">
                  <span className="mono dim">CREATED</span>
                  <span className="mono">{data.latest_reservation.created_at?.slice(0,10)}</span>
                </div>
              </div>
              <div className="timeline">
                {[
                  ["รับเรื่อง", "pending"],
                  ["อนุมัติ", "approved"],
                  ["check-in", "checked_in"],
                ].map(([label, key], i, arr) => {
                  const order = ["pending", "approved", "checked_in"];
                  const curIdx = order.indexOf(data.latest_reservation.status);
                  const done = i < curIdx;
                  const cur = i === curIdx;
                  return (
                    <React.Fragment key={key}>
                      <div className="timeline-step">
                        <div className={`timeline-dot${done ? " done" : ""}${cur ? " cur" : ""}`}>
                          {done ? "✓" : i + 1}
                        </div>
                        <div className={`timeline-label${cur ? " cur" : ""}`}>{label}</div>
                      </div>
                      {i < arr.length - 1 && (
                        <div className={`timeline-bar${done ? " done" : ""}`} />
                      )}
                    </React.Fragment>
                  );
                })}
              </div>
            </div>
          )}

          {/* Student: status callout when no reservation */}
          {role === "student" && !data.latest_reservation && (
            <div className="card dash-card dash-empty-cta">
              <div className="dash-empty-icon">{I.sparkle}</div>
              <h3 className="dash-card-title" style={{ marginBottom: 6 }}>ยังไม่เคยจอง</h3>
              <p style={{ fontSize: 13, color: "var(--ink-soft)", margin: "0 0 14px", lineHeight: 1.5 }}>
                เริ่มต้นจากการเลือกห้องที่สนใจ — เจ้าหน้าที่จะตรวจสอบและอนุมัติคำขอ
              </p>
              <button className="btn btn-primary" style={{ width: "100%", justifyContent: "center" }}
                      onClick={() => setPage("rooms")}>
                {I.bed} เลือกห้องว่าง
              </button>
            </div>
          )}

          {/* Quick action grid — common to all roles */}
          <div className="card dash-card">
            <div className="dash-card-head">
              <h3 className="dash-card-title">การดำเนินการด่วน</h3>
            </div>
            <div className="quick-grid">
              {(role === "staff" ? [
                { icon: I.doc, label: "คำขอจอง", sub: `${stats.pending_count ?? 0} รายการ`, kind: "warn", to: "reservations" },
                { icon: I.users, label: "ผู้พักทั้งหมด", sub: `${stats.total_residents ?? 0} คน`, kind: "primary", to: "residents" },
                { icon: I.bed, label: "ห้องทั้งหมด", sub: `${stats.total_rooms ?? 0} ห้อง`, kind: "ink", to: "rooms" },
                { icon: I.chart, label: "อัตราเข้าพัก", sub: `${stats.total_rooms ? Math.round((stats.total_rooms - stats.available_rooms) / stats.total_rooms * 100) : 0}%`, kind: "good", to: "home" },
              ] : role === "teacher" ? [
                { icon: I.users, label: "รายชื่อผู้พัก", sub: "read-only", kind: "primary", to: "residents" },
                { icon: I.bed, label: "ห้องทั้งหมด", sub: `${stats.total_rooms ?? 0} ห้อง`, kind: "ink", to: "rooms" },
                { icon: I.chart, label: "อัตราเข้าพัก", sub: `${stats.total_rooms ? Math.round((stats.total_rooms - stats.available_rooms) / stats.total_rooms * 100) : 0}%`, kind: "good", to: "home" },
                { icon: I.doc, label: "คำขอ pending", sub: `${stats.pending_count ?? 0} รายการ`, kind: "warn", to: "home" },
              ] : [
                { icon: I.bed, label: "ห้องว่าง", sub: `${stats.available_rooms ?? 0} ห้อง`, kind: "primary", to: "rooms" },
                { icon: I.user, label: "โปรไฟล์", sub: "ดูข้อมูล", kind: "ink", to: "me" },
                { icon: I.doc, label: "ประวัติการจอง", sub: "ทั้งหมด", kind: "good", to: "me" },
                { icon: I.home, label: "ห้องของฉัน", sub: data.current_room?.room_number || "—", kind: "warn", to: data.current_room ? `room/${data.current_room.id}` : "rooms" },
              ]).map((q, i) => (
                <button key={i} className={`quick-tile quick-${q.kind}`}
                        onClick={() => { if (q.to.includes("/")) { window.location.hash = q.to; } else { setPage(q.to); } }}>
                  <div className="quick-icon">{q.icon}</div>
                  <div className="quick-label">{q.label}</div>
                  <div className="quick-sub mono">{q.sub}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Teacher note */}
          {role === "teacher" && (
            <div className="card dash-card" style={{ background: "var(--yellow)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                <div style={{ width: 32, height: 32, background: "var(--ink)", color: "var(--yellow)",
                              display: "grid", placeItems: "center", border: "2px solid var(--ink)" }}>📚</div>
                <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700 }}>บทบาทอาจารย์</h3>
              </div>
              <p style={{ fontSize: 13, color: "var(--ink)", margin: 0, lineHeight: 1.6 }}>
                ท่านสามารถเข้าดูข้อมูลห้องและผู้พักทั้งหมดเพื่อการอ้างอิง — ไม่สามารถจองห้องหรือจัดการคำขอได้
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════
// ROOMS PAGE (student = can reserve, teacher = read-only)
// ═══════════════════════════════════════════════════════════════
const RoomsPage = ({ user, setPage }) => {
  const [data, setData] = useState(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");  // all | available | full
  const role = user?.user_type || "student";
  const readOnly = role === "teacher" || role === "staff";

  useEffect(() => { api.get("/api/rooms").then(setData).catch(console.error); }, []);

  if (!data) return <Loading />;

  const { rooms: allRooms, occupancy } = data;

  // Apply filters
  const rooms = allRooms.filter(r => {
    const occ = occupancy[r.id] || 0;
    if (query) {
      const q = query.toLowerCase();
      if (!r.room_number.toLowerCase().includes(q) &&
          !r.building.toLowerCase().includes(q)) return false;
    }
    if (filter === "available" && (r.status !== "available" || occ >= r.capacity)) return false;
    if (filter === "full" && (r.status === "available" && occ < r.capacity)) return false;
    return true;
  });

  const availCount = allRooms.filter(r => r.status === "available" && (occupancy[r.id] || 0) < r.capacity).length;
  const fullCount = allRooms.length - availCount;

  // Group by building
  const buildings = [...new Set(rooms.map(r => r.building))].sort();

  return (
    <div className="fade-up">
      {/* ─── Page header ─── */}
      <div className="page-header">
        <div>
          <div className="chip chip-primary" style={{ marginBottom: 10 }}>ROOM_DIRECTORY</div>
          <h1 className="display" style={{ fontSize: 34, margin: 0 }}>
            {readOnly ? "ห้องทั้งหมด" : "ห้องว่าง"}
          </h1>
          <p style={{ color: "var(--ink-mute)", fontSize: 14, marginTop: 6 }}>
            {readOnly ? "ข้อมูลห้องพัก — ดูอย่างเดียว" : "เลือกห้องที่ต้องการจอง"}
          </p>
        </div>
        <div className="page-header-stats">
          <div className="ph-stat">
            <div className="ph-stat-num display">{allRooms.length}</div>
            <div className="ph-stat-label mono">ทั้งหมด</div>
          </div>
          <div className="ph-stat ph-stat-good">
            <div className="ph-stat-num display">{availCount}</div>
            <div className="ph-stat-label mono">ว่าง</div>
          </div>
          <div className="ph-stat ph-stat-bad">
            <div className="ph-stat-num display">{fullCount}</div>
            <div className="ph-stat-label mono">เต็ม</div>
          </div>
        </div>
      </div>

      {/* ─── Filter bar ─── */}
      <div className="card filter-bar">
        <div className="filter-search">
          <span className="filter-search-icon">{I.search}</span>
          <input className="filter-search-input"
                 placeholder="ค้นหา เลขห้อง / ตึก..."
                 value={query}
                 onChange={e => setQuery(e.target.value)} />
        </div>
        <div className="filter-chips">
          {[
            ["all", `ทั้งหมด (${allRooms.length})`],
            ["available", `ว่าง (${availCount})`],
            ["full", `เต็ม (${fullCount})`],
          ].map(([k, label]) => (
            <button key={k}
                    className={`filter-chip${filter === k ? " active" : ""}`}
                    onClick={() => setFilter(k)}>
              {label}
            </button>
          ))}
        </div>
        <div className="filter-meta mono">
          แสดง <strong>{rooms.length}</strong>/{allRooms.length} ห้อง
        </div>
      </div>

      {buildings.map(building => {
        const bRooms = rooms.filter(r => r.building === building);
        return (
          <div key={building} style={{ marginBottom: 36 }}>
            <div className="building-header">
              <div className="building-icon">{building}</div>
              <div>
                <div className="building-name">ตึก {building}</div>
                <div className="building-sub mono">{bRooms.length} ROOMS</div>
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 16 }}>
              {bRooms.map(room => {
                const occ = occupancy[room.id] || 0;
                const pct = room.capacity > 0 ? Math.round(occ / room.capacity * 100) : 0;
                const available = room.status === "available" && occ < room.capacity;
                return (
                  <div key={room.id}
                       className={`room-card${!available ? " unavailable" : ""}`}
                       style={{ cursor: !readOnly && available ? "pointer" : "default" }}
                       onClick={() => !readOnly && available && (setPage("room"), window.location.hash = `room/${room.id}`)}>
                    <div className="slot" style={{ height: 100, marginBottom: 12, borderRadius: "var(--radius-sm)" }}>
                      ROOM · {room.room_number}
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
                      <div>
                        <div className="display" style={{ fontSize: 24 }}>{room.room_number}</div>
                        <div style={{ fontSize: 11, color: "var(--ink-mute)", fontFamily: "JetBrains Mono, monospace" }}>FL {room.floor}</div>
                      </div>
                      <StatusBadge status={available ? "available" : occ >= room.capacity ? "full" : room.status} />
                    </div>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 6 }}>
                      <span style={{ color: "var(--ink-mute)" }}>ผู้พัก</span>
                      <span className="mono" style={{ fontWeight: 700 }}>{occ}/{room.capacity}</span>
                    </div>
                    <div className="progress-track">
                      <div className={`progress-fill${pct >= 100 ? " warn" : ""}`} style={{ width: `${Math.min(pct, 100)}%` }} />
                    </div>
                    <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1.5px dashed var(--line)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span style={{ fontSize: 12, fontWeight: 700, color: available ? "var(--good)" : "var(--ink-mute)" }}>
                        {available ? `ว่าง ${room.capacity - occ} ที่` : room.status === "maintenance" ? "ปิดซ่อม" : "ไม่มีที่ว่าง"}
                      </span>
                      {!readOnly && available && (
                        <span style={{ fontSize: 12, color: "var(--primary)", fontWeight: 700 }}>ดูรายละเอียด →</span>
                      )}
                      {readOnly && (
                        <span className="chip badge-slate" style={{ fontSize: 10 }}>ดูอย่างเดียว</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}

      {rooms.length === 0 && (
        <div className="empty-state">
          <div className="empty-state-icon">{query || filter !== "all" ? "🔍" : "🏠"}</div>
          <h3>{query || filter !== "all" ? "ไม่พบห้องตามเงื่อนไข" : "ยังไม่มีห้องในระบบ"}</h3>
          <p>{query || filter !== "all" ? "ลองล้าง filter หรือเปลี่ยนคำค้น" : "ติดต่อผู้ดูแลระบบ"}</p>
          {(query || filter !== "all") && (
            <button className="btn btn-outline" style={{ marginTop: 14 }}
                    onClick={() => { setQuery(""); setFilter("all"); }}>
              ล้าง filter
            </button>
          )}
        </div>
      )}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════
// ROOM DETAIL PAGE (student only — has reserve form)
// ═══════════════════════════════════════════════════════════════
const RoomDetailPage = ({ user, roomId, setPage }) => {
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!roomId) return;
    api.get(`/api/rooms/${roomId}`).then(setData).catch(console.error);
  }, [roomId]);

  if (!data) return <Loading />;
  const { room, occupants, occupancy, active_reservation } = data;
  const pct = room.capacity > 0 ? Math.round(occupancy / room.capacity * 100) : 0;
  const canReserve = room.status === "available" && occupancy < room.capacity && !active_reservation;

  return (
    <div className="fade-up">
      {/* Breadcrumb */}
      <nav style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, marginBottom: 24, fontFamily: "JetBrains Mono, monospace", color: "var(--ink-mute)" }}>
        <a onClick={() => setPage("rooms")} style={{ cursor: "pointer", color: "var(--ink)" }}>ROOMS</a>
        <span style={{ color: "var(--yellow)" }}>▸</span>
        <span style={{ fontWeight: 700, color: "var(--primary)" }}>{room.room_number}</span>
      </nav>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 20, alignItems: "start" }}>
        {/* Left: room info */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Hero */}
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            <div className="slot" style={{ height: 160, borderRadius: 0, border: "none", borderBottom: "2px solid var(--ink)" }}>
              ROOM · {room.room_number} · {room.building}-{room.floor}
              <span style={{ position: "absolute", top: 14, right: 14 }}>
                <StatusBadge status={room.status === "available" && occupancy >= room.capacity ? "full" : room.status} />
              </span>
            </div>
            <div style={{ padding: 24 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
                <div>
                  <h1 className="display" style={{ fontSize: 52, lineHeight: 1, margin: 0 }}>{room.room_number}</h1>
                  <p style={{ fontSize: 14, color: "var(--ink-mute)", marginTop: 8 }}>
                    ตึก <strong style={{ color: "var(--ink)" }}>{room.building}</strong> · ชั้น <strong style={{ color: "var(--ink)" }}>{room.floor}</strong> · รองรับ <strong style={{ color: "var(--ink)" }}>{room.capacity}</strong> คน
                  </p>
                </div>
                <div style={{ width: 56, height: 56, background: "var(--yellow)", border: "2px solid var(--ink)", display: "grid", placeItems: "center", fontSize: 28 }}>🛏️</div>
              </div>

              {/* Stats grid */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 20 }}>
                {[
                  { label: "OCCUPIED", value: occupancy, sub: `จาก ${room.capacity} คน` },
                  { label: "AVAILABLE", value: room.capacity - occupancy,
                    valueColor: (room.capacity - occupancy) > 0 ? "var(--good)" : "var(--bad)" },
                  { label: "LOCATION", value: `${room.building}-${room.floor}`, sub: "ตึก-ชั้น" },
                ].map(s => (
                  <div key={s.label} style={{ padding: 14, background: "var(--bg-soft)", border: "2px solid var(--line)", borderRadius: "var(--radius-sm)" }}>
                    <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, fontWeight: 700, color: "var(--ink-mute)", letterSpacing: ".08em", marginBottom: 6 }}>{s.label}</div>
                    <div className="display" style={{ fontSize: 26, color: s.valueColor || "var(--ink)" }}>{s.value}</div>
                    {s.sub && <div style={{ fontSize: 11, color: "var(--ink-mute)", marginTop: 4 }}>{s.sub}</div>}
                  </div>
                ))}
              </div>

              {/* Progress */}
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 6, fontFamily: "JetBrains Mono, monospace" }}>
                  <span style={{ color: "var(--ink-mute)" }}>OCCUPANCY</span>
                  <span style={{ fontWeight: 700 }}>{occupancy}/{room.capacity} ({pct}%)</span>
                </div>
                <div className="progress-track">
                  <div className={`progress-fill${pct >= 100 ? " warn" : ""}`} style={{ width: `${Math.min(pct, 100)}%` }} />
                </div>
              </div>
            </div>
          </div>

          {/* Occupants */}
          {occupants.length > 0 && (
            <div className="card" style={{ padding: 20 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                <h2 className="display" style={{ fontSize: 18, margin: 0 }}>👥 ผู้พักในห้องนี้</h2>
                <span className="chip">{occupants.length} คน</span>
              </div>
              <ul style={{ padding: 0, margin: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 10 }}>
                {occupants.map((r, i) => (
                  <li key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: 12, background: "var(--bg-soft)", border: "2px solid var(--line)", borderRadius: "var(--radius-sm)" }}>
                    <div className="avatar" style={{ width: 36, height: 36, fontSize: 14 }}>
                      {(r.full_name || "?")[0].toUpperCase()}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 700, color: "var(--ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.full_name}</div>
                      <div style={{ fontSize: 12, color: "var(--ink-mute)" }}>{r.email}</div>
                    </div>
                    {r.student_id && <span className="chip mono">{r.student_id}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Right: action panel */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div className="card" style={{ padding: 22 }}>
            <div className="chip chip-yellow" style={{ marginBottom: 12 }}>ACTION_PANEL</div>
            <h2 className="display" style={{ fontSize: 20, marginBottom: 18 }}>การดำเนินการ</h2>

            {active_reservation ? (
              <>
                <div className="alert alert-info" style={{ marginBottom: 14 }}>
                  <span className="alert-icon">📋</span>
                  <div>
                    <strong style={{ display: "block", marginBottom: 4 }}>คุณมี Reservation อยู่แล้ว</strong>
                    สถานะ: <StatusBadge status={active_reservation.status} />
                  </div>
                </div>
                <button className="btn btn-outline" style={{ width: "100%", justifyContent: "center" }}
                        onClick={() => setPage("me")}>
                  {I.user} ดูโปรไฟล์ → จัดการ
                </button>
              </>
            ) : !canReserve ? (
              <>
                <div className="alert alert-danger" style={{ marginBottom: 14 }}>
                  <span className="alert-icon">🔒</span>
                  <div>
                    <strong style={{ display: "block", marginBottom: 4 }}>ห้องนี้ไม่พร้อมจอง</strong>
                    <span style={{ color: "var(--ink-soft)" }}>
                      {room.status === "maintenance" ? "อยู่ระหว่างซ่อมบำรุง" : occupancy >= room.capacity ? "ผู้พักเต็มแล้ว" : room.status}
                    </span>
                  </div>
                </div>
                <button className="btn btn-outline" style={{ width: "100%", justifyContent: "center" }}
                        onClick={() => setPage("rooms")}>
                  ← ดูห้องอื่น
                </button>
              </>
            ) : (
              <>
                <div className="alert alert-success" style={{ marginBottom: 18 }}>
                  <span className="alert-icon">✅</span>
                  <div>ห้องนี้ว่าง — สามารถส่งคำขอจองได้</div>
                </div>
                <form action={`/reservation/rooms/${room.id}/reserve`} method="post" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                  <div>
                    <label style={{ display: "block", fontSize: 12, fontWeight: 700, marginBottom: 6, fontFamily: "JetBrains Mono, monospace", letterSpacing: ".06em" }}>
                      REASON <span style={{ color: "var(--ink-mute)", fontWeight: 500 }}>(ไม่บังคับ)</span>
                    </label>
                    <textarea name="reason" rows="3" className="form-textarea"
                              placeholder="ระบุเหตุผลหรือความต้องการพิเศษ..."
                              style={{ resize: "none" }} />
                  </div>
                  <button type="submit" className="btn btn-primary" style={{ justifyContent: "center", padding: 14 }}>
                    {I.arrow} ส่งคำขอจองห้องนี้
                  </button>
                  <p style={{ fontSize: 11, textAlign: "center", color: "var(--ink-mute)", margin: 0 }}>
                    หลังส่งคำขอ ต้องรอ Staff อนุมัติก่อน check-in
                  </p>
                </form>
              </>
            )}
          </div>

          <button className="btn btn-outline" style={{ width: "100%", justifyContent: "center" }}
                  onClick={() => setPage("rooms")}>
            ← กลับหน้าห้องทั้งหมด
          </button>
        </div>
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════
// STAFF / TEACHER ME PAGE (work profile + recent actions)
// ═══════════════════════════════════════════════════════════════
const ACTION_LABELS = {
  approve_reservation: { icon: "✅", label: "อนุมัติคำขอจอง", color: "good" },
  reject_reservation:  { icon: "❌", label: "ปฏิเสธคำขอจอง",  color: "danger" },
  check_in_resident:   { icon: "🏠", label: "Check-in ผู้พัก",  color: "good" },
  check_out_resident:  { icon: "🚪", label: "Check-out ผู้พัก", color: "warn" },
  create_reservation:  { icon: "📝", label: "สร้างคำขอจอง",   color: "info" },
  cancel_reservation:  { icon: "🗑️", label: "ยกเลิกคำขอจอง",  color: "warn" },
};

const StaffMePage = ({ user, setPage }) => {
  const [data, setData] = useState(null);

  useEffect(() => { api.get("/api/me").then(setData).catch(console.error); }, []);

  if (!data) return <Loading />;
  const { work_stats: ws, recent_actions } = data;
  const role = user.user_type;

  const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString("th-TH", { year: "numeric", month: "short", day: "numeric" }) : "—";
  const fmtTime = (iso) => iso ? new Date(iso).toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" }) : "";
  const fmtRel = (iso) => {
    if (!iso) return "—";
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60) return "เมื่อสักครู่";
    if (diff < 3600) return `${Math.floor(diff / 60)} นาทีก่อน`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} ชั่วโมงก่อน`;
    if (diff < 604800) return `${Math.floor(diff / 86400)} วันก่อน`;
    return fmtDate(iso);
  };

  const roleLabel = role === "staff" ? "เจ้าหน้าที่" : "อาจารย์";
  const roleScopeLabel = role === "staff" ? "STAFF_SCOPE" : "TEACHER_SCOPE";

  return (
    <div className="fade-up">
      <div className="page-header">
        <div>
          <div className="chip chip-primary" style={{ marginBottom: 10 }}>USER_PROFILE</div>
          <h1 className="display" style={{ fontSize: 34, margin: 0 }}>โปรไฟล์ของฉัน</h1>
          <p style={{ color: "var(--ink-mute)", fontSize: 14, marginTop: 6 }}>
            ข้อมูลจาก Central Auth Hub + กิจกรรมการจัดการในระบบหอพัก
          </p>
        </div>
        <div className="page-header-stats">
          <div className="ph-stat ph-stat-good">
            <div className="ph-stat-num display">{ws?.pending_reservations ?? 0}</div>
            <div className="ph-stat-label mono">รออนุมัติ</div>
          </div>
          <div className="ph-stat">
            <div className="ph-stat-num display">{ws?.my_actions_this_month ?? 0}</div>
            <div className="ph-stat-label mono">ทำเดือนนี้</div>
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 24 }}>
        {/* Hub info — เหมือนของ student */}
        <div className="card" style={{ padding: 24 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 20 }}>
            <div className="avatar avatar-lg">{(user.full_name || "?")[0].toUpperCase()}</div>
            <div>
              <h2 className="display" style={{ fontSize: 20, margin: 0 }}>{user.full_name}</h2>
              <p style={{ fontSize: 13, margin: "4px 0 0", color: "var(--ink-mute)", fontFamily: "JetBrains Mono, monospace" }}>{user.email}</p>
              <StatusBadge status={user.user_type} />
            </div>
          </div>

          <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, fontWeight: 700, color: "var(--ink)", letterSpacing: ".12em", marginBottom: 12 }}>
            HUB_DATA · scope ปัจจุบัน {((user.provided_scope || []).length + 2)} fields
          </div>
          <dl style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            {(() => {
              const scope = user.provided_scope || [];
              const ALL_FIELDS = [
                ["student_id", "🎓 รหัสนักศึกษา"],
                ["employee_id", "👔 รหัสบุคลากร"],
                ["faculty", "🏛️ คณะ"],
                ["major", "📚 สาขา"],
                ["year", "🗓️ ชั้นปี"],
                ["position", "💼 ตำแหน่ง"],
                ["phone", "📞 โทรศัพท์"],
                ["address", "🏠 ที่อยู่"],
              ];
              const items = [
                ["📧 อีเมล", user.email],
                ["👤 ชื่อ-นามสกุล", user.full_name],
              ];
              ALL_FIELDS.forEach(([key, label]) => {
                if (scope.includes(key)) {
                  items.push([label, user[key] || "— ไม่มีใน Hub"]);
                }
              });
              return items.map(([label, value], i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 0", borderBottom: "1px solid var(--line-soft)" }}>
                  <dt style={{ fontSize: 13, color: "var(--ink-mute)" }}>{label}</dt>
                  <dd style={{ fontSize: 13, fontWeight: 700, margin: 0, fontFamily: "JetBrains Mono, monospace" }}>{value}</dd>
                </div>
              ));
            })()}
          </dl>
          <div style={{ marginTop: 6, fontSize: 11, color: "var(--ink-mute)", fontFamily: "JetBrains Mono, monospace" }}>
            scope: [email, name{(user.provided_scope || []).map(s => `, ${s}`).join("")}]
          </div>

          <div style={{ marginTop: 14, padding: 12, background: "var(--bg-soft)", border: "2px solid var(--line)", borderRadius: "var(--radius-sm)", fontSize: 12, color: "var(--ink-soft)", display: "flex", gap: 8 }}>
            <span>ℹ️</span>
            <span>ข้อมูลนี้มาจาก Hub ตาม JWT scope — หากต้องการแก้ไข กรุณาติดต่อ admin มหาวิทยาลัย</span>
          </div>
        </div>

        {/* Work stats — replaces DORM_STATUS for staff/teacher */}
        <div className="card" style={{ padding: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
            <h2 className="display" style={{ fontSize: 20, margin: 0 }}>
              {role === "staff" ? "🛠️" : "📊"} ขอบเขตงานของ{roleLabel}
            </h2>
            <span className="chip mono">{roleScopeLabel}</span>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {[
              { icon: "🏘️", label: "TOTAL_RESIDENTS",      value: `${ws?.total_residents ?? 0} คน`,            sub: `จัดการได้ทั้งหมด` },
              { icon: "🛏️", label: "TOTAL_ROOMS",          value: `${ws?.total_rooms ?? 0} ห้อง`,             sub: `ในระบบหอพัก` },
              { icon: "⏳", label: "PENDING_RESERVATIONS", value: `${ws?.pending_reservations ?? 0} รายการ`,  sub: `รออนุมัติ` },
              { icon: "✅", label: "APPROVED_THIS_MONTH",  value: `${ws?.approved_this_month ?? 0} รายการ`,  sub: `อนุมัติเดือนนี้` },
              ws?.first_action_at && {
                icon: "🕐", label: "FIRST_ACTION", value: fmtDate(ws.first_action_at), sub: `เริ่มทำงานในระบบ`,
              },
            ].filter(Boolean).map((item, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: 14, background: "var(--bg-soft)", border: "2px solid var(--line)", borderRadius: "var(--radius-sm)" }}>
                <span style={{ fontSize: 22 }}>{item.icon}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, fontWeight: 700, color: "var(--ink-mute)", letterSpacing: ".08em", marginBottom: 2 }}>{item.label}</div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
                    <div style={{ fontWeight: 700, color: "var(--ink)" }}>{item.value}</div>
                    <div style={{ fontSize: 11, color: "var(--ink-mute)" }}>{item.sub}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {ws?.pending_reservations > 0 && role === "staff" && (
            <button
              className="btn btn-primary"
              style={{ width: "100%", justifyContent: "center", marginTop: 14 }}
              onClick={() => setPage("reservations")}
            >
              {I.doc} ดูคำขอที่รออนุมัติ ({ws.pending_reservations})
            </button>
          )}
        </div>
      </div>

      {/* Recent actions table — replaces reservation history */}
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ padding: "18px 24px", display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "2px solid var(--ink)" }}>
          <h2 className="display" style={{ fontSize: 20, margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
            {I.doc} ประวัติการทำงานล่าสุด
          </h2>
          <span className="chip mono">{(recent_actions || []).length} รายการ</span>
        </div>

        {(recent_actions || []).length > 0 ? (
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>เวลา</th>
                  <th>การกระทำ</th>
                  <th>ประเภทเป้าหมาย</th>
                  <th>รายละเอียด</th>
                </tr>
              </thead>
              <tbody>
                {recent_actions.map((a, i) => {
                  const def = ACTION_LABELS[a.action] || { icon: "•", label: a.action, color: "default" };
                  return (
                    <tr key={i}>
                      <td>
                        <div style={{ fontWeight: 700 }}>{fmtRel(a.created_at)}</div>
                        <div style={{ fontSize: 10, color: "var(--ink-mute)", fontFamily: "JetBrains Mono, monospace" }}>
                          {fmtDate(a.created_at)} · {fmtTime(a.created_at)}
                        </div>
                      </td>
                      <td>
                        <span className={`chip chip-${def.color}`}>
                          <span style={{ marginRight: 4 }}>{def.icon}</span>{def.label}
                        </span>
                      </td>
                      <td style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 12, color: "var(--ink-soft)" }}>
                        {a.target_type || "—"}
                      </td>
                      <td style={{ fontSize: 12, color: "var(--ink-soft)", maxWidth: 280 }}>
                        {(() => {
                          const m = a.metadata || {};
                          const keys = Object.keys(m).filter(k => k !== "ip" && k !== "user_agent");
                          if (!keys.length) return <span style={{ color: "var(--ink-mute)" }}>—</span>;
                          return (
                            <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 11, lineHeight: 1.4 }}>
                              {keys.slice(0, 3).map(k => (
                                <div key={k}>
                                  <span style={{ color: "var(--ink-mute)" }}>{k}:</span>{" "}
                                  <span>{String(m[k]).slice(0, 60)}</span>
                                </div>
                              ))}
                            </div>
                          );
                        })()}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state" style={{ padding: "32px 16px" }}>
            <div className="empty-state-icon">📋</div>
            <h3>ยังไม่มีกิจกรรมในระบบ</h3>
            <p>เมื่อคุณอนุมัติ / ปฏิเสธคำขอ หรือจัดการผู้พัก จะแสดงที่นี่</p>
          </div>
        )}
      </div>
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════
// ME PAGE (student profile + history)
// ═══════════════════════════════════════════════════════════════
const MePage = ({ user, setPage }) => {
  const [data, setData] = useState(null);

  useEffect(() => { api.get("/api/me").then(setData).catch(console.error); }, []);

  if (!data) return <Loading />;
  const { resident, current_room, reservations } = data;

  const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString("th-TH", { year: "numeric", month: "short", day: "numeric" }) : "—";
  const fmtTime = (iso) => iso ? new Date(iso).toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" }) : "";

  const activeRes = reservations.filter(({ reservation: r }) => !r.cancelled_at && (r.status === "pending" || r.status === "approved" || r.status === "checked_in")).length;

  return (
    <div className="fade-up">
      <div className="page-header">
        <div>
          <div className="chip chip-primary" style={{ marginBottom: 10 }}>USER_PROFILE</div>
          <h1 className="display" style={{ fontSize: 34, margin: 0 }}>โปรไฟล์ของฉัน</h1>
          <p style={{ color: "var(--ink-mute)", fontSize: 14, marginTop: 6 }}>ข้อมูลจาก Central Auth Hub + ประวัติการจอง</p>
        </div>
        <div className="page-header-stats">
          <div className="ph-stat ph-stat-good">
            <div className="ph-stat-num display">{activeRes}</div>
            <div className="ph-stat-label mono">active</div>
          </div>
          <div className="ph-stat">
            <div className="ph-stat-num display">{reservations.length}</div>
            <div className="ph-stat-label mono">ทั้งหมด</div>
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 24 }}>
        {/* Hub info */}
        <div className="card" style={{ padding: 24 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 20 }}>
            <div className="avatar avatar-lg">{(user.full_name || "?")[0].toUpperCase()}</div>
            <div>
              <h2 className="display" style={{ fontSize: 20, margin: 0 }}>{user.full_name}</h2>
              <p style={{ fontSize: 13, margin: "4px 0 0", color: "var(--ink-mute)", fontFamily: "JetBrains Mono, monospace" }}>{user.email}</p>
              <StatusBadge status={user.user_type} />
            </div>
          </div>

          <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, fontWeight: 700, color: "var(--ink)", letterSpacing: ".12em", marginBottom: 12 }}>
            HUB_DATA · scope ปัจจุบัน {((user.provided_scope || []).length + 2)} fields
          </div>
          <dl style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            {(() => {
              const scope = user.provided_scope || [];
              const ALL_FIELDS = [
                ["student_id", "🎓 รหัสนักศึกษา"],
                ["employee_id", "👔 รหัสบุคลากร"],
                ["faculty", "🏛️ คณะ"],
                ["major", "📚 สาขา"],
                ["year", "🗓️ ชั้นปี"],
                ["position", "💼 ตำแหน่ง"],
                ["phone", "📞 โทรศัพท์"],
                ["address", "🏠 ที่อยู่"],
              ];
              // แสดง email + name เสมอ + optional fields ที่อยู่ใน scope
              const items = [
                ["📧 อีเมล", user.email],
                ["👤 ชื่อ-นามสกุล", user.full_name],
              ];
              ALL_FIELDS.forEach(([key, label]) => {
                if (scope.includes(key)) {
                  items.push([label, user[key] || "— ไม่มีใน Hub"]);
                }
              });
              return items.map(([label, value], i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 0", borderBottom: "1px solid var(--line-soft)" }}>
                  <dt style={{ fontSize: 13, color: "var(--ink-mute)" }}>{label}</dt>
                  <dd style={{ fontSize: 13, fontWeight: 700, margin: 0, fontFamily: "JetBrains Mono, monospace" }}>{value}</dd>
                </div>
              ));
            })()}
          </dl>
          <div style={{ marginTop: 6, fontSize: 11, color: "var(--ink-mute)", fontFamily: "JetBrains Mono, monospace" }}>
            scope: [email, name{(user.provided_scope || []).map(s => `, ${s}`).join("")}]
          </div>

          <div style={{ marginTop: 14, padding: 12, background: "var(--bg-soft)", border: "2px solid var(--line)", borderRadius: "var(--radius-sm)", fontSize: 12, color: "var(--ink-soft)", display: "flex", gap: 8 }}>
            <span>ℹ️</span>
            <span>ข้อมูลนี้มาจาก Hub ตาม JWT scope — หากต้องการแก้ไข กรุณาติดต่อ admin มหาวิทยาลัย</span>
          </div>
        </div>

        {/* Dorm status */}
        <div className="card" style={{ padding: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
            <h2 className="display" style={{ fontSize: 20, margin: 0 }}>🏠 สถานะในระบบหอพัก</h2>
            <span className="chip mono">DORM_STATUS</span>
          </div>

          {resident ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {[
                { icon: resident.status === "checked_in" ? "🏠" : "✅", label: "STATUS", value: resident.status },
                { icon: "🛏️", label: "CURRENT_ROOM",
                  value: current_room ? `${current_room.room_number} (ตึก ${current_room.building} ชั้น ${current_room.floor})` : "ยังไม่ได้ check-in" },
                resident.checked_in_at && { icon: "📅", label: "CHECKED_IN_AT", value: `${fmtDate(resident.checked_in_at)} · ${fmtTime(resident.checked_in_at)}` },
                { icon: "🕐", label: "FIRST_LOGIN", value: fmtDate(resident.created_at) },
              ].filter(Boolean).map((item, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: 14, background: "var(--bg-soft)", border: "2px solid var(--line)", borderRadius: "var(--radius-sm)" }}>
                  <span style={{ fontSize: 22 }}>{item.icon}</span>
                  <div>
                    <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, fontWeight: 700, color: "var(--ink-mute)", letterSpacing: ".08em", marginBottom: 2 }}>{item.label}</div>
                    <div style={{ fontWeight: 700, color: "var(--ink)" }}>{item.value}</div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-state" style={{ padding: "32px 16px" }}>
              <div className="empty-state-icon">🏠</div>
              <h3>ยังไม่มีข้อมูลในระบบ</h3>
              <p>เริ่มส่งคำขอจองห้องเพื่อสร้างโปรไฟล์</p>
            </div>
          )}

          {!current_room && user.user_type !== "staff" && user.user_type !== "teacher" && (
            <button className="btn btn-primary" style={{ width: "100%", justifyContent: "center", marginTop: 14 }}
                    onClick={() => setPage("rooms")}>
              {I.bed} ดูห้องว่างและจอง
            </button>
          )}
        </div>
      </div>

      {/* Reservation history */}
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ padding: "18px 24px", display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "2px solid var(--ink)" }}>
          <h2 className="display" style={{ fontSize: 20, margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
            {I.doc} ประวัติการจอง
          </h2>
          <span className="chip mono">{reservations.length} รายการ</span>
        </div>

        {reservations.length > 0 ? (
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>ห้อง</th>
                  <th>ตึก / ชั้น</th>
                  <th>วันที่ขอ</th>
                  <th>สถานะ</th>
                  <th>หมายเหตุ</th>
                  <th style={{ textAlign: "right" }}>การจัดการ</th>
                </tr>
              </thead>
              <tbody>
                {reservations.map(({ reservation: r, room: rm }, i) => (
                  <tr key={i}>
                    <td>
                      <a onClick={() => { setPage("room"); window.location.hash = `room/${rm.id}`; }}
                         style={{ fontWeight: 700, cursor: "pointer", color: "var(--ink)" }}>
                        {rm.room_number}
                      </a>
                    </td>
                    <td><span className="mono" style={{ fontSize: 12, color: "var(--ink-mute)" }}>{rm.building}-{rm.floor}</span></td>
                    <td>
                      <div className="mono" style={{ fontSize: 12, color: "var(--ink-mute)" }}>{fmtDate(r.created_at)}</div>
                      <div className="mono" style={{ fontSize: 11, color: "var(--ink-mute)", opacity: .7 }}>{fmtTime(r.created_at)}</div>
                    </td>
                    <td><StatusBadge status={r.cancelled_at ? "cancelled" : r.status} /></td>
                    <td style={{ maxWidth: 180 }}>
                      {r.status === "rejected" && r.reject_reason
                        ? <span style={{ fontSize: 12, color: "var(--bad)" }}>❌ {r.reject_reason}</span>
                        : r.reason
                        ? <span style={{ fontSize: 12, color: "var(--ink-mute)" }}>{r.reason}</span>
                        : <span style={{ fontSize: 12, color: "var(--ink-mute)" }}>—</span>}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {(r.status === "pending" || r.status === "approved") && !r.cancelled_at ? (
                        <form action={`/reservation/${r.id}/cancel`} method="post" style={{ display: "inline" }}
                              onSubmit={e => !confirm("ยืนยันการยกเลิก?") && e.preventDefault()}>
                          <button type="submit" className="btn btn-xs btn-danger">ยกเลิก</button>
                        </form>
                      ) : (
                        <span style={{ fontSize: 12, color: "var(--ink-mute)" }}>—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state" style={{ border: "none", borderRadius: 0 }}>
            <div className="empty-state-icon">📋</div>
            <h3>ยังไม่เคยส่งคำขอจอง</h3>
            <p>ไปที่ <a onClick={() => setPage("rooms")} style={{ color: "var(--primary)", fontWeight: 700, cursor: "pointer", textDecoration: "underline" }}>ห้องทั้งหมด</a> เพื่อเริ่มจอง</p>
          </div>
        )}
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════
// STAFF RESERVATIONS PAGE
// ═══════════════════════════════════════════════════════════════
const StaffReservationsPage = () => {
  const [data, setData] = useState(null);
  const [activeTab, setActiveTab] = useState("pending");

  const load = useCallback((status) => {
    api.get(`/staff/api/reservations?status=${status}`).then(setData).catch(console.error);
  }, []);

  useEffect(() => { load(activeTab); }, [activeTab]);

  const changeTab = (s) => { setActiveTab(s); setData(null); };

  const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString("th-TH", { month: "short", day: "numeric", year: "numeric" }) : "—";
  const fmtTime = (iso) => iso ? new Date(iso).toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" }) : "";

  const tabs = [
    { id: "pending", label: "รออนุมัติ", icon: "⏳" },
    { id: "approved", label: "อนุมัติแล้ว", icon: "✅" },
    { id: "checked_in", label: "Check-in แล้ว", icon: "🏠" },
    { id: "rejected", label: "ปฏิเสธแล้ว", icon: "❌" },
    { id: "all", label: "ทั้งหมด", icon: "📋" },
  ];

  const currentCount = data?.rows?.length ?? 0;

  return (
    <div className="fade-up">
      <div className="page-header">
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <span className="chip chip-primary">👔 STAFF</span>
            <span className="mono" style={{ fontSize: 11, color: "var(--ink-mute)", letterSpacing: ".08em" }}>RESERVATION_MGMT</span>
          </div>
          <h1 className="display" style={{ fontSize: 34, margin: 0 }}>คำขอจองห้องพัก</h1>
          <p style={{ color: "var(--ink-mute)", fontSize: 14, marginTop: 6 }}>อนุมัติ · ปฏิเสธ · check-in ผู้พัก</p>
        </div>
        <div className="page-header-stats">
          <div className={`ph-stat ${activeTab === "pending" ? "ph-stat-warn" : ""}`}>
            <div className="ph-stat-num display">{currentCount}</div>
            <div className="ph-stat-label mono">แสดงอยู่</div>
          </div>
        </div>
      </div>

      {/* Tab bar */}
      <div className="tab-bar">
        {tabs.map(t => (
          <button key={t.id} className={`tab-btn${activeTab === t.id ? " active" : ""}`}
                  onClick={() => changeTab(t.id)} style={{ cursor: "pointer" }}>
            <span>{t.icon}</span> {t.label}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {!data ? <Loading /> : data.rows.length > 0 ? (
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>ผู้ขอจอง</th>
                  <th>ห้อง</th>
                  <th>วันที่ขอ</th>
                  <th>สถานะ</th>
                  <th>เหตุผล</th>
                  <th style={{ textAlign: "right", minWidth: 180 }}>การจัดการ</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map(({ reservation: r, room: rm, resident: res }, i) => (
                  <tr key={i} style={r.status === "pending" ? { background: "#FFF8E0" } : {}}>
                    <td>
                      {res ? (
                        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                          <div className="avatar" style={{ width: 32, height: 32, fontSize: 13 }}>{(res.full_name || "?")[0].toUpperCase()}</div>
                          <div>
                            <div style={{ fontWeight: 700, color: "var(--ink)" }}>{res.full_name}</div>
                            <div className="mono" style={{ fontSize: 11, color: "var(--ink-mute)" }}>{res.email}</div>
                            {res.student_id && <div className="mono" style={{ fontSize: 10, color: "var(--ink-mute)", opacity: .7 }}>{res.student_id}</div>}
                          </div>
                        </div>
                      ) : <span style={{ fontSize: 13, color: "var(--ink-mute)" }}>ไม่มีโปรไฟล์</span>}
                    </td>
                    <td>
                      <div style={{ fontWeight: 700, color: "var(--ink)" }}>{rm.room_number}</div>
                      <div className="mono" style={{ fontSize: 11, color: "var(--ink-mute)" }}>{rm.building}-{rm.floor}</div>
                    </td>
                    <td>
                      <div className="mono" style={{ fontSize: 12, color: "var(--ink)" }}>{fmtDate(r.created_at)}</div>
                      <div className="mono" style={{ fontSize: 11, color: "var(--ink-mute)" }}>{fmtTime(r.created_at)}</div>
                    </td>
                    <td><StatusBadge status={r.status} /></td>
                    <td style={{ maxWidth: 160 }}>
                      {r.status === "rejected" && r.reject_reason
                        ? <span style={{ fontSize: 12, color: "var(--bad)" }}>⚠️ {r.reject_reason}</span>
                        : r.reason
                        ? <span style={{ fontSize: 12, color: "var(--ink-mute)" }}>{r.reason}</span>
                        : <span style={{ fontSize: 12, color: "var(--ink-mute)" }}>—</span>}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, flexWrap: "wrap" }}>
                        {r.status === "pending" && (
                          <>
                            <form action={`/staff/reservations/${r.id}/approve`} method="post" style={{ display: "inline" }}>
                              <button type="submit" className="btn btn-xs btn-success">{I.check} อนุมัติ</button>
                            </form>
                            <RejectPopover reservationId={r.id} />
                          </>
                        )}
                        {r.status === "approved" && (
                          <form action={`/staff/reservations/${r.id}/checkin`} method="post" style={{ display: "inline" }}>
                            <button type="submit" className="btn btn-xs btn-primary">🏠 Check-in</button>
                          </form>
                        )}
                        {r.status !== "pending" && r.status !== "approved" && (
                          <span style={{ fontSize: 12, color: "var(--ink-mute)" }}>—</span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state" style={{ border: "none", borderRadius: 0 }}>
            <div className="empty-state-icon">
              {activeTab === "pending" ? "⏳" : activeTab === "approved" ? "✅" : activeTab === "checked_in" ? "🏠" : "📋"}
            </div>
            <h3>ไม่มีคำขอจองในสถานะนี้</h3>
            <p>ลองเปลี่ยน filter ด้านบน</p>
          </div>
        )}
      </div>
    </div>
  );
};

const RejectPopover = ({ reservationId }) => {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button type="button" className="btn btn-xs btn-danger" onClick={() => setOpen(!open)}>
        {I.x} ปฏิเสธ
      </button>
      {open && (
        <div className="card" style={{ position: "absolute", right: 0, top: "calc(100% + 8px)", width: 280, zIndex: 30, padding: 16 }}>
          <p style={{ fontSize: 12, fontWeight: 700, marginBottom: 8, fontFamily: "JetBrains Mono, monospace", letterSpacing: ".06em" }}>REJECT_REASON</p>
          <form action={`/staff/reservations/${reservationId}/reject`} method="post" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <textarea name="reject_reason" rows="2" required className="form-textarea"
                      placeholder="ระบุเหตุผล..." style={{ resize: "none" }} />
            <button type="submit" className="btn btn-sm btn-danger" style={{ width: "100%", justifyContent: "center" }}>
              ยืนยันการปฏิเสธ
            </button>
          </form>
        </div>
      )}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════
// RESIDENTS PAGE (staff = with actions, teacher = read-only)
// ═══════════════════════════════════════════════════════════════
const ResidentsPage = ({ user }) => {
  const [data, setData] = useState(null);
  const role = user?.user_type || "student";
  const isStaff = role === "staff";

  useEffect(() => {
    const url = isStaff ? "/staff/api/residents" : "/api/teacher/residents";
    api.get(url).then(setData).catch(console.error);
  }, [isStaff]);

  const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString("th-TH", { month: "short", day: "numeric", year: "numeric" }) : "—";

  if (!data) return <Loading />;

  const rows = data.rows || [];
  const stats = data.stats || { total: rows.length, with_room: rows.filter(r => r.room).length };

  return (
    <div className="fade-up">
      <div className="page-header">
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <span className="chip chip-primary">{isStaff ? "👔 STAFF" : "📚 TEACHER"}</span>
            <span className="mono" style={{ fontSize: 11, color: "var(--ink-mute)", letterSpacing: ".08em" }}>RESIDENT_DIRECTORY</span>
          </div>
          <h1 className="display" style={{ fontSize: 34, margin: 0 }}>ผู้พักทั้งหมด</h1>
          <p style={{ color: "var(--ink-mute)", fontSize: 14, marginTop: 6 }}>
            {isStaff ? "รายชื่อผู้ที่เคย login เข้าระบบหอพัก" : "รายชื่อผู้พักทั้งหมด — ดูอย่างเดียว"}
          </p>
        </div>
        <div className="page-header-stats">
          <div className="ph-stat">
            <div className="ph-stat-num display">{stats.total}</div>
            <div className="ph-stat-label mono">ทั้งหมด</div>
          </div>
          <div className="ph-stat ph-stat-good">
            <div className="ph-stat-num display">{stats.with_room}</div>
            <div className="ph-stat-label mono">มีห้อง</div>
          </div>
          <div className="ph-stat ph-stat-warn">
            <div className="ph-stat-num display">{stats.total - stats.with_room}</div>
            <div className="ph-stat-label mono">รอ</div>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {rows.length > 0 ? (
          <div style={{ overflowX: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>ชื่อ - อีเมล</th>
                  <th>รหัส</th>
                  <th>คณะ</th>
                  <th>Role</th>
                  <th>ห้องพัก</th>
                  <th>สถานะ</th>
                  <th>Check-in เมื่อ</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ resident: r, room: rm }, i) => (
                  <tr key={i} style={rm ? { background: "#F0FBF5" } : {}}>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div className="avatar" style={{ width: 32, height: 32, fontSize: 12, background: r.user_type === "staff" ? "var(--pink)" : "var(--primary)" }}>
                          {(r.full_name || "?")[0].toUpperCase()}
                        </div>
                        <div>
                          <div style={{ fontWeight: 700, color: "var(--ink)" }}>{r.full_name}</div>
                          <div className="mono" style={{ fontSize: 11, color: "var(--ink-mute)" }}>{r.email}</div>
                        </div>
                      </div>
                    </td>
                    <td><span className="mono" style={{ fontSize: 13, color: "var(--ink)" }}>{r.student_id || "—"}</span></td>
                    <td style={{ fontSize: 13, color: "var(--ink-soft)" }}>{r.faculty || "—"}</td>
                    <td><StatusBadge status={r.user_type} /></td>
                    <td>
                      {rm ? (
                        <>
                          <span style={{ fontWeight: 700, color: "var(--ink)" }}>{rm.room_number}</span>
                          <div className="mono" style={{ fontSize: 11, color: "var(--ink-mute)", marginTop: 2 }}>{rm.building}-{rm.floor}</div>
                        </>
                      ) : <span style={{ fontSize: 13, color: "var(--ink-mute)" }}>ยังไม่มีห้อง</span>}
                    </td>
                    <td><StatusBadge status={r.status} /></td>
                    <td>
                      {r.checked_in_at ? (
                        <>
                          <div className="mono" style={{ fontSize: 12, color: "var(--ink)" }}>{fmtDate(r.checked_in_at)}</div>
                        </>
                      ) : <span style={{ fontSize: 13, color: "var(--ink-mute)" }}>—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state" style={{ border: "none", borderRadius: 0 }}>
            <div className="empty-state-icon">👥</div>
            <h3>ยังไม่มีผู้พักในระบบ</h3>
            <p>ผู้ใช้จะปรากฏที่นี่หลังจาก login ครั้งแรก</p>
          </div>
        )}
      </div>
    </div>
  );
};

// ─── Add CSS keyframe for spinner ─────────────────────────────
const style = document.createElement("style");
style.textContent = `@keyframes spin { to { transform: rotate(360deg); } }`;
document.head.appendChild(style);

// ═══════════════════════════════════════════════════════════════
// ROOT APP
// ═══════════════════════════════════════════════════════════════
const App = () => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [{ page, param }, setRoute] = useState(getHash);

  // Fetch session user on mount
  useEffect(() => {
    api.get("/api/me")
      .then(d => { setUser(d.user); setLoading(false); })
      .catch(() => { window.location.href = "/login"; });
  }, []);

  // Listen for hash changes
  useEffect(() => {
    const onHash = () => setRoute(getHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const setPage = useCallback((p) => {
    setRoute({ page: p, param: null });
    window.location.hash = p;
  }, []);

  if (loading) {
    return (
      <div style={{ height: "100dvh", display: "flex", alignItems: "center", justifyContent: "center",
                    background: "var(--bg)", fontFamily: "Anuphan, sans-serif" }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>🏠</div>
          <div style={{ fontSize: 16, color: "var(--ink-mute)" }}>กำลังโหลด...</div>
        </div>
      </div>
    );
  }

  const role = user?.user_type || "student";

  // Render page content
  const renderPage = () => {
    // Room detail — any role that can see rooms
    if (page === "room" && param) {
      if (role === "staff") return <div className="loading-state">Staff ไม่สามารถจองห้องได้</div>;
      return <RoomDetailPage user={user} roomId={param} setPage={setPage} />;
    }

    switch (page) {
      case "home":         return <HomePage user={user} setPage={setPage} />;
      case "rooms":        return <RoomsPage user={user} setPage={setPage} />;
      case "me":           return (role === "staff" || role === "teacher")
                                  ? <StaffMePage user={user} setPage={setPage} />
                                  : <MePage user={user} setPage={setPage} />;
      case "reservations": return role === "staff"
                                  ? <StaffReservationsPage />
                                  : <HomePage user={user} setPage={setPage} />;
      case "residents":    return (role === "staff" || role === "teacher")
                                  ? <ResidentsPage user={user} />
                                  : <HomePage user={user} setPage={setPage} />;
      default:             return <HomePage user={user} setPage={setPage} />;
    }
  };

  return (
    <div className="app-shell">
      <SideNav user={user} page={page} setPage={setPage} />
      <div className="app-content">
        <TopBar user={user} />
        <main className="page-main">
          {renderPage()}
        </main>
      </div>
    </div>
  );
};

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
