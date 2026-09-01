"""Policy Gate — ข้อบังคับตายตัว แยกออกจากการประเมินความเสี่ยง.

เหตุผลที่ต้องแยก: บางอย่าง "ปฏิเสธได้เลย" โดยไม่ต้องคาดการณ์อะไร เช่น IP อยู่ใน
deny-list ที่ผู้ดูแลตั้งไว้ หรือล้มเหลวเกินเกณฑ์ brute-force · สิ่งเหล่านี้ไม่ใช่
"ความเสี่ยง" แต่เป็น**นโยบาย** ถ้าปล่อยให้ปนอยู่ในชั้นให้คะแนน จะเกิดสองปัญหา:

1. ชั้นให้คะแนนกลายเป็นผู้ตัดสินสิทธิ์ไปด้วย (เดิม `RuleResult.blocked` ทำแบบนั้น)
2. ตัวเลขประสิทธิภาพของโมเดลปนกับผลของนโยบาย แยกไม่ออกว่าอะไรจับได้เพราะอะไร

**เกณฑ์แบ่ง:** ถ้าเป็นข้อเท็จจริงที่ตรวจได้แน่นอน ไม่ต้องอนุมาน -> Policy Gate ·
ถ้าเป็นการอนุมานจากพฤติกรรม (แม้จะแรงมาก) -> หลักฐานให้ L4 ตัดสิน

ตัวอย่างที่ **ย้ายมา** Policy Gate: IP deny-list · brute-force lockout ·
ข้อบังคับ step-up จากข้อเท็จจริง (เครื่องใหม่ สิทธิ์เพิ่งเปลี่ยน)

ตัวอย่างที่ **ไม่ย้าย** (เป็นหลักฐาน): impossible travel — เดิม hard block แต่
เป็นการอนุมาน (VPN / roaming / GeoIP คลาดเคลื่อน ทำให้เกิดได้) จึงกลายเป็น
หลักฐานระดับสูงสุดของ L1 ให้ L4 ตัดสินร่วมกับชั้นอื่นแทน
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.services.ip_blacklist import is_blacklisted
from app.security.rule_engine import FEAT, HARD_BLOCK_RULES, SCORE_RULES_SPEC

# ข้อบังคับ step-up — เอาเฉพาะกฎที่ **ประกาศ** ว่าเป็น policy_floor
# ห้ามอนุมานจากการมี min_action เพราะการแก้น้ำหนักคะแนนจะเปลี่ยนนโยบายโดยไม่ตั้งใจ
# (ดูคำอธิบายเต็มที่ rule_engine.SCORE_RULES_SPEC)
POLICY_STEPUP_RULES = [
    (r["feature"], r["op"], r["threshold"], r["min_action"])
    for r in SCORE_RULES_SPEC
    if r["kind"] == "policy_floor"
]

_ACTION_RANK = {None: 0, "warn": 1, "challenge": 2}


@dataclass
class PolicyOutcome:
    """ผลของนโยบาย — เป็นสิ่งเดียวนอก L4 ที่มีอำนาจต่อการเข้าถึง.

    `denied`      ปฏิเสธทันที ไม่ต้องประเมินความเสี่ยงต่อ
    `min_action`  บังคับอย่างน้อยระดับนี้ (`warn` / `challenge`) แม้คะแนนเสี่ยงต่ำ
    """

    denied: bool = False
    min_action: str | None = None
    reasons: list[str] = field(default_factory=list)
    policy: str | None = None

    @property
    def intervenes(self) -> bool:
        return self.denied or self.min_action is not None

    def to_contract(self) -> dict:
        return {
            "denied": self.denied,
            "min_action": self.min_action,
            "policy": self.policy,
            "reasons": list(self.reasons),
        }


def evaluate_policy(
    features: list[float],
    db: Session | None,
    user_id: str,
    ip: str | None,
    geo_country: str | None = None,
) -> PolicyOutcome:
    """ตรวจข้อบังคับตายตัวทั้งหมด — เรียก **ก่อน** ประเมินความเสี่ยง.

    fail-safe: DB ไม่พร้อม -> ข้ามเฉพาะกฎที่ต้องใช้ DB ไม่ปฏิเสธผู้ใช้เพราะระบบพัง
    """
    # ── deny-list ที่ผู้ดูแลตั้งเอง ──
    if ip and db is not None:
        try:
            if is_blacklisted(db, ip):
                return PolicyOutcome(
                    denied=True,
                    reasons=[f"ip_blacklisted ({ip})"],
                    policy="ip_denylist",
                )
        except Exception:  # noqa: BLE001
            pass  # DB พัง -> ไม่ปฏิเสธ ปล่อยให้ชั้นความเสี่ยงทำงานต่อ

    # ── brute-force / abuse lockout ──
    for feat_name, op, threshold in HARD_BLOCK_RULES:
        value = features[FEAT[feat_name]]
        if op == ">=" and value >= threshold:
            return PolicyOutcome(
                denied=True,
                reasons=[f"{feat_name}={value:.0f} >= {threshold}"],
                policy="abuse_lockout",
            )

    # ── ข้อบังคับ step-up จากข้อเท็จจริง (ไม่ปฏิเสธ แต่บังคับยืนยันตัวตนเพิ่ม) ──
    floor: str | None = None
    reasons: list[str] = []
    for feat_name, op, threshold, action in POLICY_STEPUP_RULES:
        value = features[FEAT[feat_name]]
        hit = (
            (op == ">=" and value >= threshold)
            or (op == "<=" and value <= threshold)
            or (op == "==" and value == threshold)
        )
        if hit:
            if _ACTION_RANK[action] > _ACTION_RANK[floor]:
                floor = action
            reasons.append(f"{feat_name}={value:.0f} -> {action}")

    if floor:
        return PolicyOutcome(
            min_action=floor, reasons=reasons, policy="mandatory_stepup"
        )
    return PolicyOutcome()
