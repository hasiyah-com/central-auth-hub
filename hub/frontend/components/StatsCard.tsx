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
  return (
    <div className={clsx("relative min-h-[132px] overflow-hidden rounded-xl border border-ink-200 bg-gradient-to-br to-white p-5", t.wash)}>
      <span className={clsx("absolute inset-y-0 left-0 w-[3px]", t.edge)} />
      <div className="flex items-start justify-between gap-3">
        <div className="text-[11px] font-semibold uppercase tracking-[.12em] text-ink-500">{label}</div>
        {icon && (
          <div className="grid h-7 w-7 place-items-center rounded-full border border-ink-200 bg-white" aria-hidden="true">
            <span className="h-1.5 w-1.5 rounded-full bg-current opacity-60" />
          </div>
        )}
      </div>
      <div className={clsx("mt-4 font-display text-[30px] font-extrabold leading-none tabular-nums", t.value)}>{value}</div>
      {sub && <div className="mt-2 text-[11px] leading-snug text-ink-500">{sub}</div>}
    </div>
  );
}
