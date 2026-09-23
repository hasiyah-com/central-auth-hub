"""align schema drift: server defaults ที่ hub_db มีแต่ migration chain ไม่มี

พบตอนทำ baseline ให้เริ่มจากฐานว่างได้ (2026-09-22): ฐานว่าง -> head เทียบกับ hub_db ทีละรายการ
ต่างกันเฉพาะ default สามคอลัมน์ · ทำให้ทุกฐาน (ฐานใหม่, hub_db, production) เหมือนกัน
รันซ้ำได้ (SET DEFAULT) · ไม่แตะข้อมูล

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-22
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a7b8c9d0e1f2"  # pragma: allowlist secret
down_revision: Union[str, None] = "f6a7b8c9d0e1"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE login_sessions ALTER COLUMN is_attack_ip SET DEFAULT false")
    op.execute(
        "ALTER TABLE login_sessions ALTER COLUMN is_account_takeover SET DEFAULT false"
    )
    op.execute(
        "ALTER TABLE subsystems ALTER COLUMN allowed_roles "
        "SET DEFAULT '{user}'::character varying[]"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE login_sessions ALTER COLUMN is_attack_ip DROP DEFAULT")
    op.execute(
        "ALTER TABLE login_sessions ALTER COLUMN is_account_takeover DROP DEFAULT"
    )
    op.execute(
        "ALTER TABLE subsystems ALTER COLUMN allowed_roles SET DEFAULT '{user}'::text[]"
    )
