import clsx from "clsx";

const TONES = {
  default: "border-ink-200 bg-ink-50 text-ink-700",
  good: "border-emerald-200 bg-emerald-50 text-emerald-700",
  warn: "border-amber-200 bg-amber-50 text-amber-700",
  danger: "border-rose-200 bg-rose-50 text-rose-700",
  brand: "border-brand-200 bg-brand-50 text-brand-700",
  pink: "border-violet-200 bg-violet-50 text-violet-700",
} as const;

export function Badge({ children, tone = "default" }: { children: React.ReactNode; tone?: keyof typeof TONES }) {
  return <span className={clsx("inline-flex items-center rounded-full border px-2.5 py-1 font-mono text-[10px] font-semibold uppercase tracking-wide", TONES[tone])}>{children}</span>;
}
