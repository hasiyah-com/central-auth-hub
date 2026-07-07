// Incident Summary — types ตรงกับ backend app/services/incident_service.py

export type IncidentRow = {
  id: string;
  created_at: string | null;
  user_id: string | null;
  user_email: string | null;
  full_name: string | null;
  user_type: string | null;
  channel_label: string;
  target: string;
  is_subsystem: boolean;
  risk_score: number | null;
  decision: string | null;
  ip: string | null;
  geo_country: string | null;
  is_attack_ip: boolean;
  status: "active" | "ended" | "expired";
  top_reason: string | null;
};

export type IncidentListResponse = {
  items: IncidentRow[];
  total: number;
  skip: number;
  limit: number;
  window_hours: number;
  kpis: {
    total: number;
    blocked: number;
    challenged: number;
    attack_ip: number;
  };
};

export type Recommendation = {
  severity: "critical" | "warning" | "info";
  title: string;
  detail: string;
  action_label?: string;
  action_href?: string;
};

export type ActionCategory =
  | "root_cause"
  | "authentication"
  | "network"
  | "account"
  | "subsystem"
  | "configuration";

export type IncidentAction = {
  type: string;
  category: ActionCategory;
  severity: "critical" | "warning" | "info";
  title: string;
  detail: string;
  button_label: string;
  executable: boolean;
  enabled: boolean;
  href?: string;
};

export type ShapContribution = {
  feature: string;
  value: number;
  shap: number;
  direction: "anomaly" | "normal";
};

export type AttackPathNode = {
  label: string;
  sublabel: string;
  kind: "source" | "channel" | "hub" | "target" | "outcome";
  status: "normal" | "danger" | "blocked" | "warn" | "ok";
};

export type TimelineEvent = {
  at: string | null;
  action: string;
  metadata: Record<string, unknown> | null;
};

export type RiskLayer = {
  key: string;
  label: string;
  value: number;
  max: number;
  desc: string;
};

export type IncidentDetail = {
  id: string;
  incident_display_id: string;
  created_at: string | null;
  risk_level: "critical" | "high" | "medium" | "low";
  entry: {
    login_method: string | null;
    channel_label: string;
    endpoint: string;
    target: string;
    is_subsystem: boolean;
    auth_method: string;
    client_app: string;
    scopes: string[];
    scopes_kind: "oauth" | "role";
    role: string | null;
    first_seen: string | null;
    last_seen: string | null;
    ip: string | null;
    geo_country: string | null;
    geo_city: string | null;
    device_type: string | null;
    browser: string | null;
    os_name: string | null;
    user_agent: string | null;
    network: string;
  };
  risk: {
    score: number;
    level: "critical" | "high" | "medium" | "low";
    level_label: string;
    decision: string | null;
    top_reasons: { raw: string; feature: string; detail: string }[];
    layers: RiskLayer[];
    shap: ShapContribution[] | null;
    anomaly_raw: number | null;
  };
  summary: { why: string; what: string; what_to_do: string };
  impact: {
    attempt_blocked: boolean;
    token_issued: boolean;
    data_exposure: boolean;
    session_killed: boolean;
    shadow_mode: boolean;
    statements: { ok: boolean; text: string }[];
  };
  attack_path: AttackPathNode[];
  reasons: { raw: string; feature: string; detail: string }[];
  timeline: TimelineEvent[];
  system_response: {
    decision: string | null;
    shadow_mode: boolean;
    action_taken: string;
    token_issued: boolean;
    session_created: boolean;
    refresh_issued: boolean;
    session_status: "active" | "ended" | "expired";
    log_saved: boolean;
  };
  recommendations: Recommendation[];
  actions: IncidentAction[];
  stats_7d: {
    total_incidents: number;
    avg_risk: number | null;
    blocked_attempts: number;
    passkey_success_rate: number | null;
    last_password_login: string | null;
  };
  related_links: { label: string; href: string }[];
  user: {
    id: string | null;
    email: string | null;
    full_name: string | null;
    user_type: string | null;
    status: string | null;
  };
};

export const DECISION_TONE: Record<
  string,
  "danger" | "warn" | "good" | "default" | "pink" | "brand"
> = {
  block: "danger",
  would_block: "danger",
  challenge: "warn",
  would_mfa: "warn",
  would_challenge: "warn",
  mfa: "warn",
  mfa_required: "warn",
  mfa_passed: "good",
  allow: "good",
};

export const STATUS_META: Record<
  string,
  { label: string; tone: "danger" | "good" | "default" }
> = {
  active: { label: "🔴 ยังเปิดอยู่", tone: "danger" },
  ended: { label: "✓ ถูกตัดแล้ว", tone: "good" },
  expired: { label: "หมดอายุแล้ว", tone: "default" },
};

export const SEVERITY_META: Record<
  string,
  { tone: "danger" | "warn" | "default"; icon: string; label: string; btn: string }
> = {
  critical: { tone: "danger", icon: "🔴", label: "ด่วน", btn: "bg-rose-600 hover:bg-rose-700" },
  warning: { tone: "warn", icon: "🟠", label: "ควรตรวจ", btn: "bg-amber-600 hover:bg-amber-700" },
  info: { tone: "default", icon: "🔵", label: "ข้อมูล", btn: "bg-emerald-600 hover:bg-emerald-700" },
};

export const RISK_LEVEL_META: Record<
  string,
  { label: string; tone: "danger" | "warn" | "default" }
> = {
  critical: { label: "HIGH RISK", tone: "danger" },
  high: { label: "HIGH RISK", tone: "danger" },
  medium: { label: "MEDIUM", tone: "warn" },
  low: { label: "LOW", tone: "default" },
};

export const ACTION_CATEGORY_META: Record<
  string,
  { label: string; icon: string }
> = {
  root_cause: { label: "Root Cause — จัดการต้นเหตุ", icon: "🎯" },
  authentication: { label: "Authentication — ยืนยันตัวตน", icon: "🔑" },
  network: { label: "Network — เครือข่าย/IP", icon: "🌐" },
  account: { label: "Account — บัญชีผู้ใช้", icon: "👤" },
  subsystem: { label: "Subsystem — ระบบย่อย", icon: "🧩" },
  configuration: { label: "Configuration — ตั้งค่าระบบ", icon: "⚙️" },
};

// สีของ node ใน attack path
export const NODE_STATUS_CLS: Record<string, string> = {
  normal: "border-ink-300 bg-white text-ink-700",
  danger: "border-rose-400 bg-rose-50 text-rose-700",
  blocked: "border-rose-500 bg-rose-500 text-white",
  warn: "border-amber-400 bg-amber-50 text-amber-700",
  ok: "border-emerald-400 bg-emerald-50 text-emerald-700",
};

// audit action → ข้อความไทยสั้นๆ สำหรับ timeline
export const AUDIT_ACTION_LABEL: Record<string, string> = {
  hub_login_blocked_by_ml: "บล็อกโดย ML (hard block)",
  risk_mfa_required: "บังคับยืนยันตัวตน (MFA)",
  risk_force_enroll_required: "บังคับลงทะเบียน Passkey",
  risk_grace_period_allowed: "อนุญาต (grace period)",
  risk_mfa_passed: "ยืนยันตัวตนผ่าน",
  risk_refresh_would_stepup: "refresh เสี่ยง (shadow — log)",
  risk_refresh_stepup_required: "refresh เสี่ยง → บังคับ Passkey",
  risk_refresh_blocked: "refresh ถูกบล็อก",
  oauth_login_failed_access_policy: "ปฏิเสธจาก Access Policy",
  user_kicked_by_deletion: "ตัดสิทธิ์ (ลบ/เปลี่ยนสถานะ user)",
  access_revoked_webhook_sent: "แจ้ง subsystem เพิกถอนสิทธิ์",
};
