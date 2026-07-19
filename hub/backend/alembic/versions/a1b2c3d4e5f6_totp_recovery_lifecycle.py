"""add totp credentials, recovery tickets, credential lifecycle status

Revision ID: a1b2c3d4e5f6
Revises: 5e31bcaf0cf4
Create Date: 2026-07-19 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"  # pragma: allowlist secret
down_revision: Union[str, None] = "5e31bcaf0cf4"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── passkey_credentials: เพิ่ม lifecycle status ──
    op.add_column(
        "passkey_credentials",
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="ACTIVE"
        ),
    )
    op.create_index(
        op.f("ix_passkey_credentials_status"),
        "passkey_credentials",
        ["status"],
        unique=False,
    )
    # backfill: row ที่ revoke ไปแล้ว → REVOKED
    op.execute(
        "UPDATE passkey_credentials SET status = 'REVOKED' WHERE revoked_at IS NOT NULL"
    )

    # ── user_totp_credentials ──
    op.create_table(
        "user_totp_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="REGISTERED"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("enabled_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(
        op.f("ix_user_totp_credentials_user_id"),
        "user_totp_credentials",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_totp_credentials_status"),
        "user_totp_credentials",
        ["status"],
        unique=False,
    )

    # ── recovery_tickets ──
    op.create_table(
        "recovery_tickets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("credential_type", sa.String(length=20), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "recovery_level",
            sa.String(length=10),
            nullable=False,
            server_default="NORMAL",
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column("requested_ip", postgresql.INET(), nullable=True),
        sa.Column("link_token", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_recovery_tickets_user_id"),
        "recovery_tickets",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recovery_tickets_email"), "recovery_tickets", ["email"], unique=False
    )
    op.create_index(
        op.f("ix_recovery_tickets_status"), "recovery_tickets", ["status"], unique=False
    )

    # ── recovery_ticket_approvals (four-eyes) ──
    op.create_table(
        "recovery_ticket_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_type", sa.String(length=30), nullable=True),
        sa.Column("evidence_note", sa.Text(), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["recovery_tickets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticket_id", "admin_id"),
    )
    op.create_index(
        op.f("ix_recovery_ticket_approvals_ticket_id"),
        "recovery_ticket_approvals",
        ["ticket_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("recovery_ticket_approvals")
    op.drop_table("recovery_tickets")
    op.drop_table("user_totp_credentials")
    op.drop_index(
        op.f("ix_passkey_credentials_status"), table_name="passkey_credentials"
    )
    op.drop_column("passkey_credentials", "status")
