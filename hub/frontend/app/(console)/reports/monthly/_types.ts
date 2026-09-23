/** รูปของข้อมูลจาก GET /admin/reports/monthly?month=YYYY-MM */

export type Level = "critical" | "warn" | "info";
export type Priority = "high" | "medium" | "low";

export type ApiStats = {
  requests: number;
  avg_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
  server_errors: number;
  error_rate: number | null;
};

export type Report = {
  month: string;
  range: { from: string; to: string; timezone: string };
  logins: {
    total: number;
    unique_users: number;
    allowed: number;
    challenged: number;
    blocked: number;
    success_rate: number | null;
  };
  risk: { avg: number | null; incidents: number; attack_ip: number };
  users: { new: number };
  audit: { events: number };
  daily: { date: string; total: number; challenged: number; blocked: number }[];
  by_subsystem: {
    subsystem_id: string | null;
    name: string;
    total: number;
    unique_users: number;
    blocked: number;
    challenged: number;
    block_rate: number | null;
  }[];
  login_methods: { method: string | null; total: number }[];
  geo: { country: string | null; total: number }[];
  trend: {
    month: string;
    logins: number;
    unique_users: number;
    blocked: number;
    challenged: number;
    incidents: number;
    block_rate: number | null;
  }[];
  availability: {
    samples: number;
    units: {
      unit_id: string;
      name: string;
      kind: string;
      samples: number;
      online: number;
      degraded: number;
      down: number;
      unknown: number;
      ok_pct: number | null;
    }[];
  };
  api_overall: ApiStats;
  api_performance: (ApiStats & { group: string; label: string })[];
  security_events: {
    date: string;
    source: "audit" | "api_alert";
    code: string;
    label: string;
    severity: Level;
    count: number;
  }[];
  security_summary: {
    api_alerts: { total: number; critical: number; warning: number; unresolved: number };
    ip_blacklist_added: number;
    force_logouts: number;
  };
  subsystem_status: {
    active: number;
    pending: number;
    suspended: number;
    registered_in_month: number;
    approved_in_month: number;
  };
  ml_feedback: {
    labeled: number;
    false_positive: number;
    true_positive: number;
    normal_confirmed: number;
    fp_rate: number | null;
    min_labels: number;
  };
  findings: { level: Level; code: string; text: string; basis: Record<string, unknown> }[];
  recommendations: { priority: Priority; code: string; text: string; reason: string }[];
  narrative: { summary: string; conclusion: string };
  previous: {
    month: string;
    logins_total: number;
    unique_users: number;
    blocked: number;
    challenged: number;
    incidents: number;
  };
  change_pct: {
    logins: number | null;
    unique_users: number | null;
    blocked: number | null;
    challenged: number | null;
    incidents: number | null;
  };
  unavailable: string[];
};
