// Shared types สำหรับทุกหน้า ML dashboard
// ── ตรงกับ API response ของ ml_admin.py ──

/** SHAP per-feature contribution from Layer 3 (IForest).
 *  Computed by ml-service via shap.TreeExplainer and embedded into
 *  login_sessions.risk_breakdown.iforest_explanation. Empty/missing
 *  when ML service is older or SHAP unavailable — UI gracefully omits.
 *  Sign convention: positive shap = pushed score toward anomaly,
 *  negative shap = pushed toward normal. */
export type ShapContribution = {
  feature: string;
  shap: number;
  value: number;
  direction: "anomaly" | "normal";
};

/** risk_breakdown JSON shape — base 4 numbers from Layer 4 aggregator,
 *  plus optional iforest_explanation embedded by oauth.py at login time. */
export type RiskBreakdown = {
  rule: number;
  behavior: number;
  iforest: number;
  iforest_raw: number;
  iforest_explanation?: ShapContribution[];
};

export type Anomaly = {
  session_id: string;
  user_id: string;
  user_email: string;
  // subsystem_name = null → Hub-direct (Admin Console)
  // ไม่ใช่ null → login ผ่าน OAuth ของระบบย่อย (หอพัก/ห้องสมุด)
  subsystem_name: string | null;
  subsystem_id: string | null;
  score: number;
  decision: string | null;
  ip: string | null;
  geo_country: string | null;
  geo_city: string | null;
  os_name: string | null;
  browser: string | null;
  device_type: string | null;
  is_attack_ip: boolean;
  is_account_takeover: boolean;
  risk_score: number | null;
  risk_breakdown: RiskBreakdown | null;
  risk_reasons: string[] | null;
  created_at: string;
};

export type UserSession = {
  id: string;
  score: number | null;
  decision: string | null;
  ip: string | null;
  geo_country: string | null;
  geo_city: string | null;
  os_name: string | null;
  browser: string | null;
  device_type: string | null;
  is_attack_ip: boolean;
  is_account_takeover: boolean;
  risk_score: number | null;
  risk_breakdown: RiskBreakdown | null;
  risk_reasons: string[] | null;
  created_at: string;
  feedback_label: string | null;
};

export type Overview = {
  data: {
    range: { days: number; from: string; to: string };
    total_logins: number;
    score_histogram: Array<{ bucket: string; count: number }>;
    decision_breakdown: Record<string, number>;
    top_anomalies: Anomaly[];
  };
  meta: {
    shadow_mode: boolean;
    thresholds: { block: number; mfa: number };
    sort?: "score" | "recent";
    limit?: number;
  };
};

export type ThresholdPreview = {
  data: {
    proposed: { block: number; mfa: number };
    current: { block: number; mfa: number };
    simulated_breakdown: { pass: number; mfa: number; block: number };
    current_breakdown: Record<string, number>;
    with_feedback: {
      true_positive: number;
      false_positive: number;
      precision_estimate: number | null;
    };
  };
};

export type UserTimeline = {
  data: {
    user: {
      id: string;
      email: string;
      full_name: string;
      user_type: string;
    };
    sessions: UserSession[];
    range: { days: number; from: string; to: string };
  };
};

export type FeedbackResponse = {
  session_id: string;
  label: string;
  note: string | null;
  marked_by: string;
  created_at: string;
};

// ── Constants ──

export const DECISION_TONE: Record<string, "good" | "warn" | "danger" | "default"> = {
  allow: "good",
  pass: "good",
  warn: "warn",
  challenge: "warn",
  mfa: "warn",
  block: "danger",
  would_warn: "warn",
  would_challenge: "warn",
  would_mfa: "warn",
  would_block: "danger",
  unknown: "default",
};

export const FEEDBACK_LABELS = [
  { value: "true_positive", label: "True Positive", desc: "เป็น anomaly จริง (attacker)" },
  { value: "false_positive", label: "False Positive", desc: "ไม่ใช่ anomaly (ผู้ใช้ปกติ)" },
  { value: "normal_confirmed", label: "Normal Confirmed", desc: "ยืนยันว่าปกติ" },
] as const;

// Device type → icon mapping
export const DEVICE_ICON: Record<string, string> = {
  desktop: "💻",
  mobile: "📱",
  tablet: "📟",
  bot: "🤖",
  unknown: "❓",
};

// Feature name → ป้ายภาษาไทย (อ่านง่ายใน SHAP/risk breakdown)
// ครบ 21 features — ดู docs/guides/ML_FEATURE_DATA_SOURCES.md
export const FEATURE_LABEL_TH: Record<string, string> = {
  hour_of_day: "ชั่วโมงที่ล็อกอิน",
  day_of_week: "วันในสัปดาห์",
  hours_from_typical_login_time: "ห่างจากเวลาที่ใช้ประจำ",
  is_thailand: "ล็อกอินจากไทย",
  is_new_country: "ประเทศใหม่",
  country_change_count_30d: "จำนวนประเทศใน 30 วัน",
  is_new_device: "อุปกรณ์ใหม่",
  is_new_user_agent_family: "เบราว์เซอร์ใหม่",
  log_minutes_since_last_login: "เวลาห่างจากล็อกอินก่อนหน้า",
  login_count_24h: "จำนวนล็อกอินใน 24 ชม.",
  failed_logins_24h: "ล็อกอินล้มเหลวใน 24 ชม.",
  passkey_count: "จำนวน Passkey",
  passkey_age_days: "อายุ Passkey (วัน)",
  new_passkey_recently_added: "เพิ่ง เพิ่ม Passkey",
  passkey_last_used_days: "ใช้ Passkey ล่าสุด (วัน)",
  concurrent_session_count: "เซสชันพร้อมกัน",
  active_subsystem_count: "ระบบย่อยที่ใช้พร้อมกัน",
  weekday_usage_score: "วันที่ผิดจากปกติ",
  scope_sensitivity_score: "ความอ่อนไหวของ scope",
  permission_change_age: "เพิ่งเปลี่ยนสิทธิ์ (วัน)",
  confirmed_incident_count: "เหตุการณ์เสี่ยงในอดีต",
  ever_changed_permission: "เคยเปลี่ยนสิทธิ์",
  impossible_travel_score: "เดินทางเร็วผิดปกติ",
};

/** คืนป้ายไทยของ feature (fallback เป็นชื่อดิบถ้าไม่มีใน map) */
export function featureLabelTh(name: string): string {
  return FEATURE_LABEL_TH[name] ?? name;
}
