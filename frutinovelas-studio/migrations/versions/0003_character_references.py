"""Character library and image jobs; existing video snapshots remain unchanged."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "characters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("reference_asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "name", name="uq_character_project_name"),
    )
    op.create_index("ix_characters_project_id", "characters", ["project_id"])
    # Nullable result ID is additive; no rewrite of the jobs table or existing snapshots.
    op.add_column("generation_jobs", sa.Column("kind", sa.String(16), server_default="video", nullable=False))
    op.add_column("generation_jobs", sa.Column("result_asset_id", sa.String(36), nullable=True))
    op.create_table(
        "chapter_renders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "chapter_id", sa.String(36), sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("active_chapter_id", sa.String(36), nullable=True, unique=True),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("result_path", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chapter_renders_chapter_id", "chapter_renders", ["chapter_id"])


def downgrade():
    op.drop_table("chapter_renders")
    with op.batch_alter_table("generation_jobs") as batch:
        batch.drop_column("result_asset_id")
        batch.drop_column("kind")
    op.drop_table("characters")
