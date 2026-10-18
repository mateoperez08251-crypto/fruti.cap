"""Track idempotent MCP image imports without changing existing assets or scenes."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("image_import_requests"):
        op.create_table(
            "image_import_requests",
            sa.Column("request_id", sa.String(36), primary_key=True),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade():
    op.drop_table("image_import_requests")
