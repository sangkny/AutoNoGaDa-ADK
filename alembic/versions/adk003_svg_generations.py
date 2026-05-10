"""svg_generations — SVG 생성 이력 (Phase 2 W1)

Revision ID: adk003_svg_generations
Revises: adk002_lore_decisions
Create Date: 2026-05-10

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "adk003_svg_generations"
down_revision: Union[str, None] = "adk002_lore_decisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "svg_generations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("svg_type", sa.String(length=64), nullable=False),
        sa.Column("svg_content", sa.Text(), nullable=False),
        sa.Column("cached", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_svg_generations_svg_type",
        "svg_generations",
        ["svg_type"],
        unique=False,
    )
    op.create_index(
        "ix_svg_generations_created_at",
        "svg_generations",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_svg_generations_created_at", table_name="svg_generations")
    op.drop_index("ix_svg_generations_svg_type", table_name="svg_generations")
    op.drop_table("svg_generations")
