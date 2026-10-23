"""provisional registration and subsystem-scoped invitations"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "f9a0b1c2d3e4"
down_revision = "e8f1a2b3c4d5"
branch_labels = None
depends_on = None
def upgrade() -> None:
    op.add_column("subsystems", sa.Column("self_registration_mode", sa.String(24), nullable=False, server_default="closed"))
    op.add_column("subsystems", sa.Column("allowed_email_domains", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"))
    op.add_column("access_list", sa.Column("source", sa.String(24), nullable=False, server_default="admin"))
def downgrade() -> None:
    op.drop_column("access_list", "source")
    op.drop_column("subsystems", "allowed_email_domains")
    op.drop_column("subsystems", "self_registration_mode")
