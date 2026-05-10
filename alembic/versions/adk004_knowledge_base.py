"""adk004 — 지식베이스 (pgvector 768) + 실패 패턴."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "adk004_knowledge_base"
down_revision: Union[str, None] = "adk003_svg_generations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    op.create_table(
        "adk_code_executions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("task_text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("result_text", sa.Text(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ontology_passed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("latency_ms", sa.Numeric(12, 3), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(dim=768), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["software_code_tasks.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_adk_code_executions_task_id",
        "adk_code_executions",
        ["task_id"],
        unique=False,
    )
    op.create_table(
        "adk_failure_patterns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("signature", sa.String(length=256), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sample_task", sa.Text(), nullable=True),
        sa.Column("suggestion", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signature"),
    )
    op.create_index(
        "ix_adk_failure_patterns_signature",
        "adk_failure_patterns",
        ["signature"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_adk_failure_patterns_signature", table_name="adk_failure_patterns")
    op.drop_table("adk_failure_patterns")
    op.drop_index("ix_adk_code_executions_task_id", table_name="adk_code_executions")
    op.drop_table("adk_code_executions")
