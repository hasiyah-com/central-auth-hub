// แสดงค่าฟีเจอร์ใน SHAP ให้คนอ่านเข้าใจ — ฟีเจอร์เวลาเป็นเวลาไทย
//
// Feature contract rba-23-bangkok-v1 stores hour_of_day / day_of_week in
// Bangkok time already.  Display those values directly; adding UTC+7 here
// would turn 23:00 Saturday into 06:00 Sunday.
const TH_WEEKDAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"];

function formatNumber(v: number): string {
  return Number.isInteger(v) ? v.toString() : v.toFixed(2);
}

/** ชั่วโมงไทยของ session จากรายการ SHAP (null ถ้าไม่มี hour_of_day) */
export function localHourFromShap(items: { feature: string; value: number }[]): number | null {
  const hour = items.find((i) => i.feature === "hour_of_day");
  return hour ? Math.round(hour.value) : null;
}

/** ค่าฟีเจอร์สำหรับแสดงใน SHAP — เวลาและวันเป็นเวลาไทยจาก backend แล้ว */
export function formatShapFeatureValue(
  feature: string,
  value: number,
  _hourLocal: number | null,
): string {
  if (feature === "hour_of_day") {
    const hour = ((Math.round(value) % 24) + 24) % 24;
    return `${String(hour).padStart(2, "0")}:00 น. (เวลาไทย)`;
  }
  if (feature === "day_of_week") {
    const day = ((Math.round(value) % 7) + 7) % 7;
    return `${TH_WEEKDAYS[day]} (เวลาไทย)`;
  }
  return formatNumber(value);
}
