"""login_sessions: ผลจำลอง baseline/hybrid + ที่มาของคอนฟิกที่ใช้ตอนให้คะแนน

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-15 21:30:00.000000

รองรับขั้นที่ 10 ของแผน Hybrid Shadow — บันทึกผลสองชุดต่อหนึ่ง login เพื่อวัดว่า
Isolation Forest เพิ่มประโยชน์จาก L1+L2 เท่าไร

ทำไมต้องเป็นคอลัมน์จริง ไม่ใช่ JSON อย่างเดียว:

* **ที่มาของคอนฟิก** (`shadow_epoch_id`, `risk_config_id`, `calibration_version`,
  `calibration_sha256`, `scoring_commit`) — `expert_alert_groups` มีคอลัมน์เหล่านี้
  อยู่แล้ว แต่ปัจจุบันเติมค่าจาก settings **ตอน sync** ไม่ใช่ค่าที่ใช้จริงตอนเกิดเหตุ
  ถ้าคอนฟิกเปลี่ยนกลางหน้าต่าง กลุ่มจะถูกติดป้ายผิด · เก็บที่ระดับ login จึงเป็น
  ที่เดียวที่พิสูจน์ที่มาได้จริง (บทเรียน B66 — คอนฟิกต่างกัน = คนละระบบ)
* **ผลจำลองสองชุด + ธงว่า L3 เปลี่ยนผล** — เป็นเงื่อนไขคัดเหตุการณ์เข้า Expert
  Review และเป็นตัวตั้งของ paired comparison จึงต้อง query ได้ตรง ๆ
* **eligibility / n_history** — ใช้แจกแจงอัตรา abstain ตามขนาดประวัติ (ขั้นที่ 6)

ส่วนคะแนนรายมุมมองของ L3 ยังอยู่ใน `risk_breakdown["l3"]` ตามที่แผนอนุญาตให้เก็บ
เป็น JSON ในช่วงแรก

ทุกคอลัมน์ nullable และไม่มี default — แถวเดิมยังอ่านได้เหมือนเดิม และ
`NULL` มีความหมายชัดเจนว่า "เกิดก่อนมีการบันทึกผลจำลอง" ไม่ใช่ "คำนวณแล้วได้ศูนย์"
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"  # pragma: allowlist secret
down_revision: Union[str, None] = "e5f6a7b8c9d0"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (ชื่อคอลัมน์, ชนิด) — เรียงตามกลุ่มเดียวกับใน models.py
_COLUMNS = [
    # ที่มาของการตัดสินจริง
    ("actual_decision_source", sa.String(length=32)),
    # ผลจำลอง L1+L2
    ("baseline_shadow_score", sa.Numeric(precision=4, scale=3)),
    ("baseline_shadow_decision", sa.String(length=20)),
    # ผลจำลอง L1+L2+L3
    ("hybrid_shadow_score", sa.Numeric(precision=4, scale=3)),
    ("hybrid_shadow_decision", sa.String(length=20)),
    # L3 — ส่วนที่ต้อง query ได้ตรง (คะแนนรายมุมมองอยู่ใน risk_breakdown)
    ("l3_changed_shadow_decision", sa.Boolean()),
    ("l3_eligibility", sa.String(length=20)),
    ("l3_n_history", sa.Integer()),
    # calibration + ที่มาของคอนฟิก
    ("calibrated", sa.Boolean()),
    ("calibration_version", sa.String(length=64)),
    ("calibration_sha256", sa.String(length=64)),
    ("risk_config_id", sa.String(length=64)),
    ("shadow_epoch_id", sa.String(length=64)),
    ("scoring_commit", sa.String(length=64)),
    # ต้นทุนเวลา
    ("latency_total_ms", sa.Integer()),
    ("latency_l3_ms", sa.Integer()),
]

# index เฉพาะคอลัมน์ที่ใช้คัดเหตุการณ์จริง — ไม่ใส่พร่ำเพรื่อเพราะตารางนี้เขียนทุก login
_INDEXES = [
    ("ix_login_sessions_shadow_epoch_id", "shadow_epoch_id"),
    ("ix_login_sessions_l3_changed_shadow_decision", "l3_changed_shadow_decision"),
]


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column("login_sessions", sa.Column(name, type_, nullable=True))
    for index_name, column in _INDEXES:
        op.create_index(index_name, "login_sessions", [column])


def downgrade() -> None:
    for index_name, _ in _INDEXES:
        op.drop_index(index_name, table_name="login_sessions")
    for name, _ in reversed(_COLUMNS):
        op.drop_column("login_sessions", name)
