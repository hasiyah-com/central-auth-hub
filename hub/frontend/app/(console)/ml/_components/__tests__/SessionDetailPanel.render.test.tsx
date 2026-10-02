/**
 * Render test — เหตุผลความเสี่ยงของ session จริง 2026-10-02 (คะแนน 1.000 → WOULD_CHALLENGE)
 * ต้องไม่ขึ้นป้าย HARD BLOCK ให้บรรทัด score_block_capped และต้องบอกสถานะชั้นที่ 3
 */
import { render, screen } from "@testing-library/react";
import { L3StatusLine, RuleBreakdown } from "../SessionDetailPanel";
import { l3Status } from "@/lib/riskDisplay";

const REASONS = [
  "is_new_device (+0.3)",
  "is_new_user_agent_family (+0.2)",
  "permission_change_age (+0.25)",
  "permission_change_age (+0.1)",
  "hours_diff=6.0 >= 6 (+0.20)",
  "weekend_mismatch (+0.10)",
  "score_block_capped (ไม่มีหลักฐาน hard block → challenge)",
];

describe("RuleBreakdown", () => {
  test("score_block_capped ไม่ขึ้นป้าย HARD BLOCK และแสดงเป็นหมายเหตุ", () => {
    render(<RuleBreakdown reasons={REASONS} />);
    expect(screen.queryByText("HARD BLOCK")).toBeNull();
    expect(screen.getByText(/ลดระดับ: คะแนนถึงเกณฑ์ block/)).toBeTruthy();
    expect(screen.getByText("(6)")).toBeTruthy(); // นับเฉพาะ 6 กฎที่มีน้ำหนัก
  });

  test("hard block จริงยังขึ้นป้าย HARD BLOCK", () => {
    render(<RuleBreakdown reasons={["ip_blacklisted (203.0.113.9)"]} />);
    expect(screen.getByText("HARD BLOCK")).toBeTruthy();
  });

  test("เหตุผลตัวสำรองชั้นที่ 3 แสดงเป็นหมายเหตุ", () => {
    render(<RuleBreakdown reasons={["l3_fallback_warn (L3 0.570 >= 0.4606)"]} />);
    expect(screen.getByText(/ตัวสำรองชั้นที่ 3:/)).toBeTruthy();
  });
});

describe("L3StatusLine", () => {
  test("session ในภาพ: ชั้นที่ 3 พบ (0.57) แต่ซ้ำกับชั้นที่ 1+2", () => {
    render(
      <L3StatusLine
        status={l3Status({ iforest_raw: 0.57, l3: { is_anomaly: true, unique_to_l3: false } })}
      />,
    );
    expect(screen.getByText(/ซ้ำกับชั้นที่ 1\+2/)).toBeTruthy();
  });

  test("ตัวสำรองทำงาน → บอกว่ายกเป็น warn", () => {
    render(<L3StatusLine status={l3Status({ l3_fallback: { applied: true } })} />);
    expect(screen.getByText(/ยกเป็น warn/)).toBeTruthy();
  });

  test("ชั้นที่ 3 ไม่พบ → ไม่แสดงอะไร", () => {
    const { container } = render(<L3StatusLine status={l3Status({ iforest_raw: 0.2 })} />);
    expect(container.textContent).toBe("");
  });
});
