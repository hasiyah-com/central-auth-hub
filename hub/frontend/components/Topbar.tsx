"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { CommandPalette } from "@/components/CommandPalette";

export function Topbar({ title }: { title: string }) {
  const pathname = usePathname();
  const crumb = pathname.split("/").filter(Boolean).join(" / ") || "dashboard";
  return (
    <>
      <header className="topbar">
        <div className="crumb"><span className="mono">HUB</span><i>/</i><strong>{title}</strong></div>
        <button className="search" type="button" aria-label="ค้นหาในระบบ" onClick={() => document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true, ctrlKey: true, bubbles: true }))}>
          <SearchIcon /><span>ค้นหาในระบบ...</span><kbd className="mono">⌘ K</kbd>
        </button>
        <Link className="top-icon" href="/notifications" aria-label="แจ้งเตือน"><BellIcon /></Link>
        <Clock />
        <span className="sr-only">{crumb}</span>
      </header>
      <CommandPalette />
    </>
  );
}

function Clock() {
  const [now, setNow] = useState("");
  useEffect(() => {
    const tick = () => setNow(new Date().toLocaleTimeString("th-TH", { timeZone: "Asia/Bangkok", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }));
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, []);
  return <time className="time mono"><ClockIcon />{now || "--:--:--"} ICT</time>;
}

function SearchIcon() { return <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>; }
function BellIcon() { return <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M5 17h14l-2-3V9a5 5 0 0 0-10 0v5l-2 3Z"/><path d="M10 20h4"/></svg>; }
function ClockIcon() { return <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>; }
