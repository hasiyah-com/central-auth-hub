"use client";

import { useEffect } from "react";
import clsx from "clsx";

type Props = { open: boolean; onClose: () => void; title: string; children: React.ReactNode };

export function SlidePanel({ open, onClose, title, children }: Props) {
  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) { if (event.key === "Escape") onClose(); }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => { document.body.style.overflow = ""; };
  }, [open]);

  return (
    <>
      <div className={clsx("fixed inset-0 z-40 bg-ink-900/55 backdrop-blur-[3px] transition-opacity duration-300", open ? "opacity-100" : "pointer-events-none opacity-0")} onClick={onClose} aria-hidden="true" />
      <aside role="dialog" aria-modal="true" aria-label={title} className={clsx("fixed bottom-0 right-0 top-0 z-50 flex w-[560px] max-w-full flex-col border-l border-white/10 bg-ink-900 shadow-2xl transition-transform duration-300 ease-out", open ? "translate-x-0" : "translate-x-full")}>
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_100%_0%,rgba(52,232,196,.10),transparent_24rem)]" />
        <div className="relative flex items-center justify-between border-b border-white/10 px-6 py-4">
          <div>
            <div className="font-mono text-[9px] uppercase tracking-[.18em] text-brand-500">Secure detail</div>
            <h2 className="font-display text-lg font-bold text-white">{title}</h2>
          </div>
          <button onClick={onClose} className="grid h-9 w-9 place-items-center rounded-lg border border-white/10 text-xl text-ink-400 hover:border-white/20 hover:bg-white/10 hover:text-white" aria-label="ปิด">×</button>
        </div>
        <div className="relative flex-1 overflow-y-auto bg-white px-5 py-5 sm:px-6">{children}</div>
      </aside>
    </>
  );
}
