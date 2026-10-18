"""Add managed audio and optional character voices without rewriting old revisions."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    asset_columns = {column["name"] for column in sa.inspect(bind).get_columns("assets")}
    if "duration_seconds" not in asset_columns:
        op.add_column("assets", sa.Column("duration_seconds", sa.Float(), nullable=True))
    columns = {column["name"] for column in sa.inspect(bind).get_columns("characters")}
    if "voice_description" not in columns:
        op.add_column("characters", sa.Column("voice_description", sa.Text(), nullable=False, server_default=""))
    if "voice_asset_id" not in columns:
        if bind.dialect.name == "sqlite":
            # SQLite supports this nullable inline FK without rebuilding the table.
            op.execute("ALTER TABLE characters ADD COLUMN voice_asset_id VARCHAR(36) REFERENCES assets(id)")
        else:
            op.add_column("characters", sa.Column("voice_asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=True))


def downgrade():
    with op.batch_alter_table("characters") as batch:
        batch.drop_column("voice_asset_id")
        batch.drop_column("voice_description")
    with op.batch_alter_table("assets") as batch:
        batch.drop_column("duration_seconds")
