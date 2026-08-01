/**
 * Shared pure formatters — canonical + unit-tested (lib/__tests__/format.test.ts).
 * รวม helper ที่เคยกระจาย/ซ้ำในหลายหน้า (parseUTC, relTime, riskColor, ฯลฯ)
 * เพื่อให้ทดสอบได้จริงและกันบั๊กเดิม (B53 timezone naive-UTC).
 */

/**
 * Backend ส่ง timestamp เป็น naive UTC (`datetime.isoformat()` ไม่มี `Z`/offset).
 * `new Date("2026-07-11T03:30:00")` ถูก JS ตีความเป็น local time → ที่ไทย (UTC+7)
 * เวลาที่พึ่งเกิดเพี้ยนเป็น "7 ชม.ก่อน" (B53). เติม `Z` ถ้ายังไม่มี tz designator
 * เพื่อบังคับ parse เป็น UTC ก่อนแปลงเป็น local ตอนแสดงผล.
 */
export function parseUTC(iso: string): Date {
  const hasTz = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(iso);
  return new Date(hasTz ? iso : iso + "Z");
}

/** เวลาแบบสัมพัทธ์ภาษาไทย ("เมื่อครู่" / "N นาทีก่อน" / "N ชม.ก่อน" / "N วันก่อน"). */
export function relTime(iso: string | null): string {
  if (!iso) return "—";
  const d = parseUTC(iso);
  const m = Math.floor((Date.now() - d.getTime()) / 60000);
  if (m < 1) return "เมื่อครู่";
  if (m < 60) return `${m} นาทีก่อน`;
  if (m < 1440) return `${Math.floor(m / 60)} ชม.ก่อน`;
  const day = Math.floor(m / 1440);
  if (day < 30) return `${day} วันก่อน`;
  return d.toLocaleDateString("th-TH");
}

/** ระยะเวลา (วินาที) → "Hชม Mน" / "Mน Sว" / "Sว". */
export function formatDuration(sec: number): string {
  let s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600);
  s -= h * 3600;
  const m = Math.floor(s / 60);
  s -= m * 60;
  if (h > 0) return `${h}ชม ${m}น`;
  if (m > 0) return `${m}น ${s}ว`;
  return `${s}ว`;
}

/** สีตามระดับความเสี่ยง (ตรง threshold RBA: warn 0.5 / challenge 0.7 / block 0.85). */
export function riskColor(score: number): string {
  if (score >= 0.85) return "#dc2626"; // block — แดง
  if (score >= 0.7) return "#f97316"; // challenge — ส้ม
  if (score >= 0.5) return "#eab308"; // warn — เหลือง
  return "#10b981"; // allow — เขียว
}

/** สี avatar deterministic จาก email (HSL hue). */
export function avatarColor(email: string | null): string {
  const s = email || "?";
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
  return `hsl(${h} 55% 45%)`;
}
