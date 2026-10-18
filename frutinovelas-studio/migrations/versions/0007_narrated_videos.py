"""Persist audio-first storyboard exports independently of H3 scene generations."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "narrated_videos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audio_asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False, server_default=""),
        sa.Column("aspect_ratio", sa.String(5), nullable=False, server_default="9:16"),
        sa.Column("shots", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("state", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("result_path", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_narrated_videos_project_id", "narrated_videos", ["project_id"])


def downgrade():
    op.drop_index("ix_narrated_videos_project_id", table_name="narrated_videos")
    op.drop_table("narrated_videos")
