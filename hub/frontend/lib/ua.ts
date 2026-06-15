/**
 * User-Agent parser แบบเบา (client-side) — แปลง UA string เป็น browser · OS
 * ที่อ่านง่าย สำหรับแสดงใน audit log / origin detail.
 *
 * ไม่ครอบคลุมทุก edge case (ใช้ ua-parser-js ถ้าต้องการครบ) — พอสำหรับ
 * แสดงต้นทางใน dashboard: "Edge 149 · Windows 10", "Chrome 120 · Android".
 */

export type ParsedUA = {
  browser: string; // "Edge 149" | "Chrome 120" | "—"
  os: string; // "Windows 10" | "Android" | "—"
  label: string; // "Edge 149 · Windows 10" | UA ดิบถ้า parse ไม่ได้
  raw: string;
};

function detectBrowser(ua: string): string {
  // ลำดับสำคัญ — Edge/Opera มี "Chrome" ใน UA ต้องเช็คก่อน
  const m: [RegExp, string][] = [
    [/Edg(?:e|A|iOS)?\/(\d+)/, "Edge"],
    [/OPR\/(\d+)/, "Opera"],
    [/Firefox\/(\d+)/, "Firefox"],
    [/Chrome\/(\d+)/, "Chrome"],
    [/Version\/(\d+).*Safari/, "Safari"],
  ];
  for (const [re, name] of m) {
    const r = ua.match(re);
    if (r) return `${name} ${r[1]}`;
  }
  if (/Safari/.test(ua)) return "Safari";
  return "";
}

function detectOS(ua: string): string {
  if (/Windows NT 10/.test(ua)) return "Windows 10/11";
  if (/Windows NT 6\.3/.test(ua)) return "Windows 8.1";
  if (/Windows NT/.test(ua)) return "Windows";
  if (/Android (\d+)/.test(ua)) return `Android ${ua.match(/Android (\d+)/)?.[1]}`;
  if (/iPhone OS (\d+)/.test(ua))
    return `iOS ${ua.match(/iPhone OS (\d+)/)?.[1]}`;
  if (/iPad|iPhone|iPod/.test(ua)) return "iOS";
  if (/Mac OS X/.test(ua)) return "macOS";
  if (/Linux/.test(ua)) return "Linux";
  if (/CrOS/.test(ua)) return "ChromeOS";
  return "";
}

export function parseUserAgent(ua: string | null | undefined): ParsedUA | null {
  if (!ua || typeof ua !== "string") return null;
  const browser = detectBrowser(ua) || "—";
  const os = detectOS(ua) || "—";
  const parts = [browser, os].filter((p) => p && p !== "—");
  return {
    browser,
    os,
    label: parts.length ? parts.join(" · ") : ua.slice(0, 40),
    raw: ua,
  };
}
