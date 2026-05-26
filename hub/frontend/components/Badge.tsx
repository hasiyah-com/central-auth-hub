import clsx from "clsx";

const TONES = {
  default: "bg-ink-100 text-ink-700",
  good: "bg-emerald-100 text-emerald-700",
  warn: "bg-amber-100 text-amber-700",
  danger: "bg-rose-100 text-rose-700",
  brand: "bg-brand-100 text-brand-700",
  pink: "bg-pink-100 text-pink-700",
} as const;

export function Badge({
  children,
  tone = "default",
}: {
  children: React.ReactNode;
  tone?: keyof typeof TONES;
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold",
        TONES[tone]
      )}
    >
      {children}
    </span>
  );
}
