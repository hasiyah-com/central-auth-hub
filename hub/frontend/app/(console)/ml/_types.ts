// Shared types สำหรับทุกหน้า ML dashboard
// ── ตรงกับ API response ของ ml_admin.py ──

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
  pass: "good",
  mfa: "warn",
  block: "danger",
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
