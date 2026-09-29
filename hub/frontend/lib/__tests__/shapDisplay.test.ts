/**
 * Unit tests — lib/shapDisplay: ค่าฟีเจอร์เวลาใน SHAP ต้องแสดงเป็นเวลาไทย.
 * ฟีเจอร์คำนวณจาก UTC (feature_extraction.py: now.hour / now.weekday()) —
 * ห้ามแก้ที่โมเดล แปลงเฉพาะตอนแสดงผล (UTC+7, ไทยไม่มี DST)
 */
import { formatShapFeatureValue, utcHourFromShap } from "@/lib/shapDisplay";

describe("hour_of_day → เวลาไทย", () => {
  test("18 UTC = 01:00 ไทย (ข้ามเที่ยงคืน)", () => {
    expect(formatShapFeatureValue("hour_of_day", 18, 18)).toBe("01:00 น. (เวลาไทย)");
  });
  test("0 UTC = 07:00 ไทย", () => {
    expect(formatShapFeatureValue("hour_of_day", 0, 0)).toBe("07:00 น. (เวลาไทย)");
  });
  test("16 UTC = 23:00 ไทย (ยังไม่ข้ามวัน)", () => {
    expect(formatShapFeatureValue("hour_of_day", 16, 16)).toBe("23:00 น. (เวลาไทย)");
  });
});

describe("day_of_week → วันไทย (0 = จันทร์ ตาม Python weekday)", () => {
  test("อังคาร UTC 18:00 = พุธ ไทย", () => {
    expect(formatShapFeatureValue("day_of_week", 1, 18)).toBe("พุธ (เวลาไทย)");
  });
  test("อาทิตย์ UTC 20:00 = จันทร์ ไทย (วนรอบสัปดาห์)", () => {
    expect(formatShapFeatureValue("day_of_week", 6, 20)).toBe("จันทร์ (เวลาไทย)");
  });
  test("ไม่ข้ามเที่ยงคืน = วันเดิม", () => {
    expect(formatShapFeatureValue("day_of_week", 2, 3)).toBe("พุธ (เวลาไทย)");
  });
  test("ไม่รู้ชั่วโมง → แสดงวันแบบ UTC พร้อมบอก ไม่เดา", () => {
    expect(formatShapFeatureValue("day_of_week", 1, null)).toBe("อังคาร (UTC)");
  });
});

describe("ฟีเจอร์อื่นไม่เปลี่ยน", () => {
  test("ค่าส่วนต่างชั่วโมงไม่ขึ้นกับ timezone", () => {
    expect(formatShapFeatureValue("hours_from_typical_login_time", 3, 18)).toBe("3");
  });
  test("ทศนิยม 2 ตำแหน่งเหมือนเดิม", () => {
    expect(formatShapFeatureValue("permission_change_age", 6.3912, 18)).toBe("6.39");
  });
});

describe("utcHourFromShap", () => {
  test("ดึงชั่วโมง UTC จากรายการ SHAP ทั้งหมด", () => {
    expect(
      utcHourFromShap([
        { feature: "permission_change_age", value: 6.39 },
        { feature: "hour_of_day", value: 18 },
      ]),
    ).toBe(18);
  });
  test("ไม่มี hour_of_day → null", () => {
    expect(utcHourFromShap([{ feature: "day_of_week", value: 1 }])).toBeNull();
  });
});
