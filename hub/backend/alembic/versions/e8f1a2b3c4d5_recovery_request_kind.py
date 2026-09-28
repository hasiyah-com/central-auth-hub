"""add recovery ticket request kind

Revision ID: e8f1a2b3c4d5
Revises: b7c8d9e0f1a2
Create Date: 2026-09-28 12:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8f1a2b3c4d5"  # pragma: allowlist secret
down_revision: Union[str, None] = "b7c8d9e0f1a2"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recovery_tickets",
        sa.Column(
            "request_kind",
            sa.String(length=32),
            nullable=False,
            server_default="account_recovery",
        ),
    )
    op.create_index(
        "ix_recovery_tickets_request_kind",
        "recovery_tickets",
        ["request_kind"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recovery_tickets_request_kind", table_name="recovery_tickets"
    )
    op.drop_column("recovery_tickets", "request_kind")
