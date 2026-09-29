// แสดงค่าฟีเจอร์ใน SHAP ให้คนอ่านเข้าใจ — ฟีเจอร์เวลาเป็นเวลาไทย
//
// Hub คำนวณ hour_of_day / day_of_week จากเวลา UTC (feature_extraction.py:
// now.hour, now.weekday() — 0 = จันทร์) และโปรไฟล์ก็เป็น UTC ทั้งหมด การตัดสิน
// จึงถูกต้องอยู่แล้ว แปลงเฉพาะตอนแสดงผลเท่านั้น (ไทย = UTC+7 ไม่มี DST)

const TH_OFFSET_HOURS = 7;
const TH_WEEKDAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"];

function formatNumber(v: number): string {
  return Number.isInteger(v) ? v.toString() : v.toFixed(2);
}

/** ชั่วโมง UTC ของ session จากรายการ SHAP (null ถ้าไม่มี hour_of_day) */
export function utcHourFromShap(items: { feature: string; value: number }[]): number | null {
  const hour = items.find((i) => i.feature === "hour_of_day");
  return hour ? Math.round(hour.value) : null;
}

/** ค่าฟีเจอร์สำหรับแสดงใน SHAP — hourUtc ใช้เลื่อนวันเมื่อเวลาไทยข้ามเที่ยงคืน */
export function formatShapFeatureValue(
  feature: string,
  value: number,
  hourUtc: number | null,
): string {
  if (feature === "hour_of_day") {
    const th = (Math.round(value) + TH_OFFSET_HOURS) % 24;
    return `${String(th).padStart(2, "0")}:00 น. (เวลาไทย)`;
  }
  if (feature === "day_of_week") {
    const day = Math.round(value);
    if (hourUtc === null) return `${TH_WEEKDAYS[day % 7]} (UTC)`;
    const shift = hourUtc + TH_OFFSET_HOURS >= 24 ? 1 : 0;
    return `${TH_WEEKDAYS[(day + shift) % 7]} (เวลาไทย)`;
  }
  return formatNumber(value);
}
