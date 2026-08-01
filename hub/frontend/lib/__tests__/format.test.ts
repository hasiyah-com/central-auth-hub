/**
 * Unit tests — lib/format (pure formatters). ครอบ positive + edge/negative.
 * เน้นกันบั๊ก B53 (timezone naive-UTC parse ผิดเป็น local).
 */
import {
  parseUTC,
  relTime,
  formatDuration,
  riskColor,
  avatarColor,
} from "@/lib/format";

describe("parseUTC — naive-UTC (กันบั๊ก B53)", () => {
  test("naive UTC (ไม่มี Z) → เติม Z parse เป็น UTC", () => {
    // 03:30 UTC → getUTCHours ต้องเป็น 3 (ไม่ใช่ตีความเป็น local)
    expect(parseUTC("2026-07-11T03:30:00").getUTCHours()).toBe(3);
  });
  test("มี Z อยู่แล้ว → ไม่ double-append", () => {
    expect(parseUTC("2026-07-11T03:30:00Z").getUTCHours()).toBe(3);
  });
  test("มี offset +07:00 → เคารพ offset (03:30+07 = 20:30 UTC วันก่อน)", () => {
    expect(parseUTC("2026-07-11T03:30:00+07:00").getUTCHours()).toBe(20);
  });
  test("naive UTC = เวลาปัจจุบัน → diff ~0 (ไม่เพี้ยน 7 ชม.)", () => {
    const nowNaive = new Date().toISOString().replace("Z", "");
    const diffMin = (Date.now() - parseUTC(nowNaive).getTime()) / 60000;
    expect(Math.abs(diffMin)).toBeLessThan(1); // ไม่ใช่ 420 (7ชม.)
  });
});

describe("relTime", () => {
  test("null → —", () => expect(relTime(null)).toBe("—"));
  test("เมื่อครู่ (< 1 นาที)", () => {
    const now = new Date().toISOString().replace("Z", "");
    expect(relTime(now)).toBe("เมื่อครู่");
  });
  test("N นาทีก่อน", () => {
    const t = new Date(Date.now() - 5 * 60000).toISOString().replace("Z", "");
    expect(relTime(t)).toBe("5 นาทีก่อน");
  });
  test("N ชม.ก่อน", () => {
    const t = new Date(Date.now() - 3 * 3600000).toISOString().replace("Z", "");
    expect(relTime(t)).toBe("3 ชม.ก่อน");
  });
  test("N วันก่อน", () => {
    const t = new Date(Date.now() - 2 * 86400000).toISOString().replace("Z", "");
    expect(relTime(t)).toBe("2 วันก่อน");
  });
});

describe("formatDuration", () => {
  test.each([
    [0, "0ว"],
    [45, "45ว"],
    [90, "1น 30ว"],
    [3661, "1ชม 1น"],
    [-10, "0ว"], // negative → clamp 0
  ])("%i วินาที → %s", (sec, expected) => {
    expect(formatDuration(sec as number)).toBe(expected);
  });
});

describe("riskColor — ตรง threshold RBA", () => {
  test.each([
    [0.0, "#10b981"], // allow เขียว
    [0.49, "#10b981"],
    [0.5, "#eab308"], // warn เหลือง
    [0.7, "#f97316"], // challenge ส้ม
    [0.85, "#dc2626"], // block แดง
    [1.0, "#dc2626"],
  ])("score %f → %s", (score, color) => {
    expect(riskColor(score as number)).toBe(color);
  });
});

describe("avatarColor", () => {
  test("deterministic — email เดิมได้สีเดิม", () => {
    expect(avatarColor("a@x.com")).toBe(avatarColor("a@x.com"));
  });
  test("email ต่างกันสีมักต่างกัน", () => {
    expect(avatarColor("a@x.com")).not.toBe(avatarColor("zzzzz@y.com"));
  });
  test("null → ยัง return HSL (ไม่ crash)", () => {
    expect(avatarColor(null)).toMatch(/^hsl\(/);
  });
});
