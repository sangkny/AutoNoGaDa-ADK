"""software_lore_decisions — 아키텍처 DEBATE 결정 이력 (Lore)

Revision ID: adk002_lore_decisions
Revises: adk001_create_software
Create Date: 2026-05-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "adk002_lore_decisions"
down_revision: Union[str, None] = "adk001_create_software"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "software_lore_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "decision_type",
            sa.String(length=64),
            nullable=False,
            server_default="architecture_debate",
        ),
        sa.Column("requirement", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("raw_output", sa.Text(), nullable=True),
        sa.Column("orchestrator_passed", sa.Boolean(), nullable=False),
        sa.Column("strategy", sa.String(length=32), nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False),
        sa.Column("orchestrator_task_id", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("lore_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_software_lore_decisions_created_at",
        "software_lore_decisions",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_software_lore_decisions_decision_type",
        "software_lore_decisions",
        ["decision_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_software_lore_decisions_decision_type",
        table_name="software_lore_decisions",
    )
    op.drop_index(
        "ix_software_lore_decisions_created_at",
        table_name="software_lore_decisions",
    )
    op.drop_table("software_lore_decisions")
