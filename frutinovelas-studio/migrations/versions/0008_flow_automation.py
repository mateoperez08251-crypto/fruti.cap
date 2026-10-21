"""Add an independent Flow queue without changing ComfyUI jobs or workflows."""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column(n, sa.DateTime(timezone=True), nullable=False) for n in ("created_at", "updated_at")]


def upgrade():
    op.create_table("flow_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("chapter_id", sa.String(36), sa.ForeignKey("chapters.id"), nullable=False),
        sa.Column("specification", sa.JSON(), nullable=False), *timestamps())
    op.create_table("flow_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("batch_id", sa.String(36), sa.ForeignKey("flow_batches.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("chapter_id", sa.String(36), sa.ForeignKey("chapters.id"), nullable=False),
        sa.Column("scene_id", sa.String(36), sa.ForeignKey("scenes.id"), nullable=False),
        sa.Column("active_key", sa.String(80), unique=True, nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("dependency_id", sa.String(36), nullable=True),
        sa.Column("approval", sa.String(16), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("remote_stopped", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("result_asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=True),
        sa.Column("result_path", sa.String(500), nullable=True),
        sa.Column("result_sha256", sa.String(64), nullable=True),
        sa.Column("result_mime", sa.String(64), nullable=True),
        sa.Column("result_metadata", sa.JSON(), nullable=False), *timestamps())
    for table, columns in {"flow_batches": ("project_id", "chapter_id"),
                           "flow_jobs": ("batch_id", "project_id", "chapter_id", "scene_id", "state")}.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])
    op.create_table("flow_connections",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("connected", sa.Boolean(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("agent_id", sa.String(36), nullable=False), *timestamps())


def downgrade():
    op.drop_table("flow_connections")
    op.drop_table("flow_jobs")
    op.drop_table("flow_batches")
