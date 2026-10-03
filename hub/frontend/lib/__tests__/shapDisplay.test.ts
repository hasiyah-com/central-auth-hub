/**
 * Unit tests — lib/shapDisplay: ค่าฟีเจอร์เวลาใน SHAP ต้องแสดงเป็นเวลาไทย.
 * Backend contract rba-23-bangkok-v1 คำนวณฟีเจอร์เวลาไทยไว้แล้ว
 * Frontend ต้องแสดงตรง ๆ เพื่อไม่บวก UTC+7 ซ้ำ
 */
import { formatShapFeatureValue, localHourFromShap } from "@/lib/shapDisplay";

describe("hour_of_day → เวลาไทย", () => {
  test("23 จาก backend แสดง 23:00 โดยไม่บวก 7 ซ้ำ", () => {
    expect(formatShapFeatureValue("hour_of_day", 23, 23)).toBe("23:00 น. (เวลาไทย)");
  });
  test("0 แสดง 00:00 ไทย", () => {
    expect(formatShapFeatureValue("hour_of_day", 0, 0)).toBe("00:00 น. (เวลาไทย)");
  });
  test("6 แสดง 06:00 ไทย", () => {
    expect(formatShapFeatureValue("hour_of_day", 6, 6)).toBe("06:00 น. (เวลาไทย)");
  });
});

describe("day_of_week → วันไทย (0 = จันทร์ ตาม Python weekday)", () => {
  test("วันเสาร์จาก backend ยังเป็นวันเสาร์", () => {
    expect(formatShapFeatureValue("day_of_week", 5, 23)).toBe("เสาร์ (เวลาไทย)");
  });
  test("วันอาทิตย์ยังเป็นวันอาทิตย์", () => {
    expect(formatShapFeatureValue("day_of_week", 6, 23)).toBe("อาทิตย์ (เวลาไทย)");
  });
  test("ไม่ข้ามเที่ยงคืน = วันเดิม", () => {
    expect(formatShapFeatureValue("day_of_week", 2, 3)).toBe("พุธ (เวลาไทย)");
  });
  test("ไม่รู้ชั่วโมงก็แสดงวันไทยจาก contract ได้", () => {
    expect(formatShapFeatureValue("day_of_week", 1, null)).toBe("อังคาร (เวลาไทย)");
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

describe("localHourFromShap", () => {
  test("ดึงชั่วโมงไทยจากรายการ SHAP ทั้งหมด", () => {
    expect(
      localHourFromShap([
        { feature: "permission_change_age", value: 6.39 },
        { feature: "hour_of_day", value: 18 },
      ]),
    ).toBe(18);
  });
  test("ไม่มี hour_of_day → null", () => {
    expect(localHourFromShap([{ feature: "day_of_week", value: 1 }])).toBeNull();
  });
});
