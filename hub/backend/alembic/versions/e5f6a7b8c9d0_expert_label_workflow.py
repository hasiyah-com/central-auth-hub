"""expert label workflow: expert_alert_groups, system_dispositions, expert_reviews

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-10 12:00:00.000000

แบบ: docs/design/EXPERT_LABEL_WORKFLOW.md

สามตารางแยกกันโดยตั้งใจ
  expert_alert_groups   หน่วยที่ผู้เชี่ยวชาญตรวจ (user_id, primary_signal, 30 นาที)
  system_dispositions   สิ่งที่ระบบทำ/จะทำ — เขียนครั้งเดียวตอนสร้างกลุ่ม
  expert_reviews        สิ่งที่ผู้เชี่ยวชาญวินิจฉัย — append-only ผ่าน supersedes_id

การบังคับที่ระดับฐานข้อมูล (ไม่พึ่งแค่ว่า API ไม่มี endpoint)
  * trigger ปฏิเสธ UPDATE บน expert_reviews และ system_dispositions
  * supersedes_id UNIQUE — label หนึ่งแถวถูกแก้ได้ครั้งเดียว ประวัติเป็นสายเดียว
  * FK แบบ composite (supersedes_id, group_id, reviewer_id, round) — แถวที่แก้ต้อง
    อยู่กลุ่มเดียวกัน ผู้ตรวจคนเดียวกัน และรอบเดียวกันกับแถวเดิม
  * unique index บางส่วน — label ต้นทาง (supersedes_id IS NULL) ได้แถวเดียวต่อ
    (กลุ่ม, ผู้ตรวจ, รอบ) กันการส่งซ้ำที่เลี่ยง service หรือ request ที่ชนกัน
  * CHECK รอบ 1 ต้อง model_output_visible = false · รอบ 2 ต้อง true
  * CHECK verdict / confidence / provenance อยู่ในรายการปิด
  * FK ทั้งหมดไม่ cascade — ลบผู้ใช้ กลุ่ม หรือ label ต้นทางที่ยังถูกอ้างอยู่ไม่ได้
  * created_at ใช้ timezone('utc', now()) ไม่ขึ้นกับ timezone ของ session

ตาราง feedback เดิมของ ML ไม่ถูกแตะและไม่ถูก migrate เข้ามา
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"  # pragma: allowlist secret
down_revision: Union[str, None] = "d4e5f6a7b8c9"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UTC_NOW = sa.text("timezone('utc', now())")


def upgrade() -> None:
    op.create_table(
        "expert_alert_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("group_key", sa.String(255), nullable=False, unique=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("primary_signal", sa.String(120), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("session_ids", sa.JSON(), nullable=False),
        sa.Column("n_events", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("shadow_epoch_id", sa.String(64), nullable=True),
        sa.Column("risk_config_id", sa.String(64), nullable=True),
        sa.Column("calibration_version", sa.String(64), nullable=True),
        sa.Column("calibration_sha256", sa.String(64), nullable=True),
        sa.Column("scoring_commit", sa.String(64), nullable=True),
        sa.Column("provenance", sa.String(10), nullable=False),
        sa.Column(
            "eligible_for_production_metrics",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "double_review", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=UTC_NOW),
        sa.CheckConstraint(
            "provenance IN ('demo','test','unknown','local','external')",
            name="ck_expert_alert_groups_provenance",
        ),
        sa.CheckConstraint(
            "NOT eligible_for_production_metrics OR ("
            "provenance = 'external' AND risk_config_id IS NOT NULL "
            "AND scoring_commit IS NOT NULL)",
            name="ck_expert_alert_groups_eligible",
        ),
    )
    op.create_index(
        "ix_expert_alert_groups_user_id", "expert_alert_groups", ["user_id"]
    )
    op.create_index(
        "ix_expert_alert_groups_window_start", "expert_alert_groups", ["window_start"]
    )
    op.create_index(
        "ix_expert_alert_groups_provenance", "expert_alert_groups", ["provenance"]
    )

    op.create_table(
        "system_dispositions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("expert_alert_groups.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("disposition", sa.String(20), nullable=False),
        sa.Column("decision_counts", sa.JSON(), nullable=False),
        sa.Column("max_risk_score", sa.Numeric(4, 3), nullable=True),
        sa.Column("primary_layer", sa.String(20), nullable=True),
        sa.Column("model_output", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=UTC_NOW),
    )

    op.create_table(
        "expert_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("expert_alert_groups.id"),
            nullable=False,
        ),
        sa.Column(
            "reviewer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("round", sa.SmallInteger(), nullable=False),
        sa.Column("model_output_visible", sa.Boolean(), nullable=False),
        sa.Column("verdict", sa.String(24), nullable=False),
        sa.Column("confidence", sa.String(8), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("time_spent_sec", sa.Integer(), nullable=True),
        sa.Column(
            "supersedes_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("expert_reviews.id"),
            nullable=True,
            unique=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=UTC_NOW),
        sa.CheckConstraint(
            "(round = 1 AND model_output_visible = false) OR "
            "(round = 2 AND model_output_visible = true)",
            name="ck_expert_reviews_round_visibility",
        ),
        sa.CheckConstraint(
            "verdict IN ('benign','suspicious','confirmed_attack','insufficient_context')",
            name="ck_expert_reviews_verdict",
        ),
        sa.CheckConstraint(
            "confidence IN ('low','medium','high')",
            name="ck_expert_reviews_confidence",
        ),
        # เป้าหมายของ FK แบบ composite ด้านล่าง
        sa.UniqueConstraint(
            "id", "group_id", "reviewer_id", "round", name="uq_expert_reviews_chain_key"
        ),
    )
    op.create_index("ix_expert_reviews_group_id", "expert_reviews", ["group_id"])
    op.create_index("ix_expert_reviews_reviewer_id", "expert_reviews", ["reviewer_id"])
    # แถวที่แก้ต้องอยู่กลุ่ม ผู้ตรวจ และรอบเดียวกับแถวเดิม (MATCH SIMPLE — ไม่ตรวจเมื่อ
    # supersedes_id เป็น NULL)
    op.create_foreign_key(
        "fk_expert_reviews_supersedes_same_chain",
        "expert_reviews",
        "expert_reviews",
        ["supersedes_id", "group_id", "reviewer_id", "round"],
        ["id", "group_id", "reviewer_id", "round"],
    )
    # label ต้นทางได้แถวเดียวต่อ (กลุ่ม, ผู้ตรวจ, รอบ)
    op.create_index(
        "uq_expert_reviews_one_root",
        "expert_reviews",
        ["group_id", "reviewer_id", "round"],
        unique=True,
        postgresql_where=sa.text("supersedes_id IS NULL"),
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION expert_review_forbid_update() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION USING
            MESSAGE = 'append-only table ' || TG_TABLE_NAME
                      || ': UPDATE is not allowed, insert a new row instead';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in ("expert_reviews", "system_dispositions"):
        op.execute(
            f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION expert_review_forbid_update();"
        )


def downgrade() -> None:
    for table in ("expert_reviews", "system_dispositions"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update ON {table};")
    op.execute("DROP FUNCTION IF EXISTS expert_review_forbid_update();")
    op.drop_index("ix_expert_reviews_reviewer_id", table_name="expert_reviews")
    op.drop_index("ix_expert_reviews_group_id", table_name="expert_reviews")
    # drop_table ลบ FK แบบ composite และ unique index บางส่วนไปพร้อมตาราง
    op.drop_table("expert_reviews")
    op.drop_table("system_dispositions")
    op.drop_index("ix_expert_alert_groups_provenance", table_name="expert_alert_groups")
    op.drop_index(
        "ix_expert_alert_groups_window_start", table_name="expert_alert_groups"
    )
    op.drop_index("ix_expert_alert_groups_user_id", table_name="expert_alert_groups")
    op.drop_table("expert_alert_groups")
