import clsx from "clsx";

type Props = {
  label: string;
  value: string | number;
  sub?: string;
  icon?: string;
  tone?: "default" | "good" | "warn" | "danger" | "brand";
};

const TONES: Record<NonNullable<Props["tone"]>, { edge: string; value: string; wash: string }> = {
  default: { edge: "bg-ink-400", value: "text-ink-900", wash: "from-ink-50/70" },
  good: { edge: "bg-emerald-500", value: "text-emerald-700", wash: "from-emerald-50/70" },
  warn: { edge: "bg-amber-500", value: "text-amber-700", wash: "from-amber-50/70" },
  danger: { edge: "bg-rose-600", value: "text-rose-700", wash: "from-rose-50/70" },
  brand: { edge: "bg-brand-600", value: "text-brand-700", wash: "from-brand-50/70" },
};

export function StatsCard({ label, value, sub, icon, tone = "default" }: Props) {
  const t = TONES[tone];
  const cxTone = tone === "good" || tone === "brand" ? "signal" : tone === "danger" ? "danger" : "";
  return (
    <article className={clsx("cx-kpi", cxTone)}>
      <span className="mono">{label}</span>
      <strong className={t.value}>{value}</strong>
      {sub && <small>{sub}</small>}
      {icon && <i className="cx-kpi-mark" aria-hidden="true" />}
    </article>
  );
}
