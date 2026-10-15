"""Conexión remota y generaciones individuales durables."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "comfy_connections",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("identity", sa.JSON(), nullable=False),
        sa.Column("workflow", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scene_id", sa.String(36), sa.ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("active_scene_id", sa.String(36), nullable=True, unique=True),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("prompt_id", sa.String(64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("result_path", sa.String(500), nullable=True),
        sa.Column("result_mime", sa.String(64), nullable=True),
        sa.Column("result_sha256", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_generation_jobs_scene_id", "generation_jobs", ["scene_id"])
    op.create_index("ix_generation_jobs_state", "generation_jobs", ["state"])


def downgrade():
    op.drop_table("generation_jobs")
    op.drop_table("comfy_connections")
