"""Recover the additive image schema when legacy revision 0003 was incomplete.

The static v3 definitions are repeated deliberately: recovery must not depend on
future ORM models or a different migration module imported by another install.
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "characters" not in tables:
        _create_characters()
    if "ix_characters_project_id" not in {i["name"] for i in sa.inspect(bind).get_indexes("characters")}:
        op.create_index("ix_characters_project_id", "characters", ["project_id"])
    columns = {c["name"] for c in sa.inspect(bind).get_columns("generation_jobs")}
    if "kind" not in columns:
        op.add_column(
            "generation_jobs", sa.Column("kind", sa.String(16), server_default="video", nullable=False)
        )
    if "result_asset_id" not in columns:
        op.add_column("generation_jobs", sa.Column("result_asset_id", sa.String(36), nullable=True))
    if "chapter_renders" not in tables:
        _create_chapter_renders()
    if "ix_chapter_renders_chapter_id" not in {
        i["name"] for i in sa.inspect(bind).get_indexes("chapter_renders")
    }:
        op.create_index("ix_chapter_renders_chapter_id", "chapter_renders", ["chapter_id"])


def _create_characters():
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


def _create_chapter_renders():
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


def downgrade():
    # These objects belong to 0003; recovery does not remove user data on downgrade.
    pass
