"use client";

import { useEffect } from "react";
import clsx from "clsx";

type Props = {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
};

export function SlidePanel({ open, onClose, title, children }: Props) {
  // ปิดด้วย Escape key
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // ป้องกัน scroll body เมื่อ panel เปิด
  useEffect(() => {
    if (open) document.body.style.overflow = "hidden";
    else document.body.style.overflow = "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <>
      {/* Backdrop */}
      <div
        className={clsx(
          "fixed inset-0 z-40 bg-ink-900/30 transition-opacity duration-300",
          open ? "opacity-100" : "opacity-0 pointer-events-none"
        )}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <aside
        className={clsx(
          "fixed top-0 right-0 z-50 h-full w-[500px] max-w-full",
          "bg-white shadow-2xl flex flex-col",
          "transition-transform duration-300 ease-in-out",
          open ? "translate-x-0" : "translate-x-full"
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-ink-200 shrink-0">
          <h2 className="text-lg font-extrabold text-ink-900">{title}</h2>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg hover:bg-ink-100 grid place-items-center text-ink-500 hover:text-ink-900 transition text-lg"
            aria-label="ปิด"
          >
            &times;
          </button>
        </div>

        {/* Body — scrollable */}
        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
      </aside>
    </>
  );
}
