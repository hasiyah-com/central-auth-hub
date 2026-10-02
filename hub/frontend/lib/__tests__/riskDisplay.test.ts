/**
 * Unit tests — lib/riskDisplay: การแสดงเหตุผลและสถานะชั้นที่ 3 ใน Session Detail
 *
 * ที่มา: session จริง 2026-10-02 คะแนน 1.000 → WOULD_CHALLENGE
 *  - บรรทัด "score_block_capped (ไม่มีหลักฐาน hard block → challenge)" ถูกป้าย HARD BLOCK สีแดง
 *    ทั้งที่ความหมายคือ "ไม่ block" (ตัวแปลงเช็คคำว่า "hard block" ในข้อความ)
 *  - แถบ IForest แสดง 0.00 เสมอ เพราะชั้นที่ 3 ไม่บวกคะแนน ทั้งที่ตรวจพบ (raw 0.57)
 */
import { classifyReason, l3Status } from "@/lib/riskDisplay";

describe("classifyReason", () => {
  test("score_block_capped ไม่ใช่ hard block (กันป้ายผิดความหมาย)", () => {
    expect(
      classifyReason("score_block_capped (ไม่มีหลักฐาน hard block → challenge)"),
    ).toBe("capped");
  });

  test.each([
    "ip_blacklisted (203.0.113.9)",
    "impossible_travel: TH → US in 0.5h (< 1h)",
    "failed_logins_24h=10 >= 10 (hard block)",
    "login_count_24h=50 >= 50 (hard block)",
    "skipped (hard block)",
  ])("hard block จริงยังเป็น hard block: %s", (raw) => {
    expect(classifyReason(raw)).toBe("hard_block");
  });

  test("ตัวสำรองชั้นที่ 3", () => {
    expect(classifyReason("l3_fallback_warn (L3 0.570 >= 0.4606)")).toBe("l3_fallback");
  });

  test.each(["is_new_device (+0.30)", "hours_diff=6.0 >= 6 (+0.20)", "weekend_mismatch (+0.10)"])(
    "เหตุผลมีน้ำหนักทั่วไป: %s",
    (raw) => {
      expect(classifyReason(raw)).toBe("weighted");
    },
  );
});

describe("l3Status", () => {
  test("ตัวสำรองทำงาน → ยกเป็น warn", () => {
    const s = l3Status({ iforest_raw: 0.57, l3_fallback: { applied: true, threshold: 0.4606 } });
    expect(s.tone).toBe("fallback");
    expect(s.text).toContain("warn");
  });

  test("ชั้นที่ 3 พบเพิ่ม แต่ยังไม่ยกระดับ (ปิดตัวสำรอง/ข้อมูลเก่า)", () => {
    const s = l3Status({ iforest_raw: 0.7, l3: { is_anomaly: true, unique_to_l3: true } });
    expect(s.tone).toBe("unique");
  });

  test("ชั้นที่ 3 พบ แต่ชั้น 1+2 พบอยู่แล้ว → ซ้ำ ไม่นับเพิ่ม", () => {
    const s = l3Status({ iforest_raw: 0.57, l3: { is_anomaly: true, unique_to_l3: false } });
    expect(s.tone).toBe("duplicate");
    expect(s.text).toContain("ซ้ำ");
  });

  test("ชั้นที่ 3 ไม่พบความผิดปกติ → ไม่แสดงสถานะ", () => {
    expect(l3Status({ iforest_raw: 0.2, l3: { is_anomaly: false } }).tone).toBe("quiet");
  });

  test("ไม่มีข้อมูลชั้นที่ 3 (session เก่า) → quiet ไม่ error", () => {
    expect(l3Status({}).tone).toBe("quiet");
    expect(l3Status({ iforest_raw: undefined }).tone).toBe("quiet");
  });

  test("ตัวสำรองไม่ทำงานแต่มีข้อมูล → ไม่ถือว่ายกระดับ", () => {
    const s = l3Status({ iforest_raw: 0.3, l3_fallback: { applied: false, threshold: 0.4606 } });
    expect(s.tone).toBe("quiet");
  });
});
