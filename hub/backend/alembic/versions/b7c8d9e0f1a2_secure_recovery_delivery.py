"""secure recovery evidence, tracking and alternate delivery

Revision ID: b7c8d9e0f1a2
Revises: d4e5f6a7b8c9
Create Date: 2026-09-27 02:45:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c8d9e0f1a2"  # pragma: allowlist secret
down_revision: Union[str, None] = "d4e5f6a7b8c9"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recovery_tickets", sa.Column("tracking_secret_hash", sa.Text(), nullable=True))
    op.add_column("recovery_tickets", sa.Column("evidence_type", sa.String(length=30), nullable=True))
    op.add_column("recovery_tickets", sa.Column("evidence_mime", sa.String(length=50), nullable=True))
    op.add_column("recovery_tickets", sa.Column("evidence_encrypted", sa.Text(), nullable=True))
    op.add_column("recovery_tickets", sa.Column("alternate_email", sa.String(length=255), nullable=True))
    op.add_column(
        "recovery_tickets",
        sa.Column("alternate_email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "recovery_tickets",
        sa.Column("delivery_status", sa.String(length=30), nullable=False, server_default="pending"),
    )
    op.add_column("recovery_tickets", sa.Column("delivery_sent_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("recovery_tickets", "delivery_sent_at")
    op.drop_column("recovery_tickets", "delivery_status")
    op.drop_column("recovery_tickets", "alternate_email_verified")
    op.drop_column("recovery_tickets", "alternate_email")
    op.drop_column("recovery_tickets", "evidence_encrypted")
    op.drop_column("recovery_tickets", "evidence_mime")
    op.drop_column("recovery_tickets", "evidence_type")
    op.drop_column("recovery_tickets", "tracking_secret_hash")
