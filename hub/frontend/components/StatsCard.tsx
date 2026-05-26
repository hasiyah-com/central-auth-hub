import clsx from "clsx";

type Props = {
  label: string;
  value: string | number;
  sub?: string;
  icon?: string;
  tone?: "default" | "good" | "warn" | "danger" | "brand";
};

const TONES: Record<NonNullable<Props["tone"]>, string> = {
  default: "from-ink-50 to-white text-ink-900 border-ink-200",
  good: "from-emerald-50 to-white text-emerald-700 border-emerald-200",
  warn: "from-amber-50 to-white text-amber-700 border-amber-200",
  danger: "from-rose-50 to-white text-rose-700 border-rose-200",
  brand: "from-brand-50 to-white text-brand-700 border-brand-200",
};

export function StatsCard({ label, value, sub, icon, tone = "default" }: Props) {
  return (
    <div
      className={clsx(
        "rounded-xl border bg-gradient-to-br p-5 shadow-sm",
        TONES[tone]
      )}
    >
      <div className="flex items-start justify-between">
        <div className="text-xs font-semibold uppercase tracking-wider text-ink-500">
          {label}
        </div>
        {icon && <div className="text-xl opacity-60">{icon}</div>}
      </div>
      <div className="mt-3 text-3xl font-extrabold leading-none">{value}</div>
      {sub && <div className="mt-2 text-xs text-ink-500">{sub}</div>}
    </div>
  );
}
