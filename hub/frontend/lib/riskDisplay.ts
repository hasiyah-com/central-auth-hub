// การแสดงเหตุผลความเสี่ยงและสถานะชั้นที่ 3 ใน Session Detail — เฉพาะส่วนแสดงผล ไม่แตะการให้คะแนน

export type ReasonKind = "hard_block" | "capped" | "l3_fallback" | "weighted";

/** แยกชนิดของเหตุผลจากข้อความที่ Hub บันทึก (risk_reasons) */
export function classifyReason(raw: string): ReasonKind {
  // บันทึกว่าคะแนนถึงเกณฑ์ block แต่ไม่มีหลักฐาน hard block → ลดเป็น challenge
  // ข้อความมีคำว่า "hard block" แต่ความหมายคือ "ไม่ block" จึงต้องเช็คก่อน
  if (raw.startsWith("score_block_capped")) return "capped";
  if (raw.startsWith("l3_fallback_warn")) return "l3_fallback";
  if (
    raw.includes("hard block") ||
    raw.startsWith("ip_blacklisted") ||
    raw.startsWith("impossible_travel")
  ) {
    return "hard_block";
  }
  return "weighted";
}

export type L3Tone = "fallback" | "unique" | "duplicate" | "quiet";
export type L3Status = { tone: L3Tone; text: string };

type L3Input = {
  iforest_raw?: number;
  l3?: { is_anomaly?: boolean; unique_to_l3?: boolean };
  l3_fallback?: { applied?: boolean; threshold?: number };
};

/**
 * สถานะของชั้นที่ 3 ต่อการเข้าสู่ระบบหนึ่งครั้ง
 *  - fallback : ชั้นที่ 1+2 ตัดสิน allow แต่ชั้นที่ 3 ตรวจพบ → ยกเป็น warn (ตัวสำรอง)
 *  - unique   : ชั้นที่ 3 พบเพิ่มที่ชั้นที่ 1+2 ไม่พบ แต่ยังไม่ยกระดับ (บันทึกเฝ้าระวัง)
 *  - duplicate: ชั้นที่ 3 พบ แต่ชั้นที่ 1+2 พบอยู่แล้ว → ไม่นับเพิ่ม (กันนับซ้ำ)
 *  - quiet    : ชั้นที่ 3 ไม่พบความผิดปกติ หรือไม่มีข้อมูล (session เก่า)
 */
export function l3Status(bd: L3Input): L3Status {
  if (bd.l3_fallback?.applied) {
    return { tone: "fallback", text: "ชั้นที่ 3 ตรวจพบสิ่งที่ชั้นที่ 1+2 พลาด → ยกเป็น warn" };
  }
  if (bd.l3?.is_anomaly && bd.l3?.unique_to_l3) {
    return {
      tone: "unique",
      text: "ชั้นที่ 3 ตรวจพบสิ่งที่ชั้นที่ 1+2 พลาด (บันทึกเฝ้าระวัง ยังไม่ยกระดับ)",
    };
  }
  if (bd.l3?.is_anomaly) {
    return {
      tone: "duplicate",
      text: "ชั้นที่ 3 ตรวจพบด้วย แต่ซ้ำกับชั้นที่ 1+2 จึงไม่นับเพิ่ม",
    };
  }
  return { tone: "quiet", text: "" };
}
