"""add login_sessions.last_seen_at (presence heartbeat for online detection)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-22 20:00:00.000000

เดิม "online" ตรวจจาก created_at อยู่ใน JWT window (15 นาที) ซึ่งไม่ตรงจริง:
ปิดแท็บไม่กด logout ยังโชว์ online จนครบ 15 นาที + คน active เกิน 15 นาที (refresh
token) กลับหายไป. เพิ่ม last_seen_at ที่ bump ทุกครั้งที่ Hub เห็น activity จริง
(refresh + heartbeat ping) → online = last_seen ภายในหน้าต่างสั้นๆ.

Backfill = created_at เพื่อไม่ให้ session เดิมกลายเป็น offline ทันทีตอน migrate.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"  # pragma: allowlist secret
down_revision: Union[str, None] = "c3d4e5f6a7b8"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "login_sessions",
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
    )
    # backfill = created_at (session เดิมจะใช้ created_at เป็นจุดอ้างอิงเหมือนพฤติกรรมเก่า)
    op.execute("UPDATE login_sessions SET last_seen_at = created_at")
    op.create_index(
        "ix_login_sessions_last_seen_at", "login_sessions", ["last_seen_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_login_sessions_last_seen_at", table_name="login_sessions")
    op.drop_column("login_sessions", "last_seen_at")
