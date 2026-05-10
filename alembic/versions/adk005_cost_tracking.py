"""adk005 — 모델 사용 로그 + 월 예산."""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "adk005_cost_tracking"
down_revision: Union[str, None] = "adk004_knowledge_base"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "adk_model_usage_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("complexity", sa.String(length=32), nullable=False),
        sa.Column("selected_model", sa.String(length=128), nullable=False),
        sa.Column("estimated_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actual_cost_usd", sa.Numeric(18, 8), nullable=True),
        sa.Column("ontology_passed", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_adk_model_usage_logs_task_id",
        "adk_model_usage_logs",
        ["task_id"],
        unique=False,
    )

    op.create_table(
        "adk_monthly_budget",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("year_month", sa.String(length=7), nullable=False),
        sa.Column("budget_usd", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "spent_usd",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("year_month"),
    )
    op.create_index(
        "ix_adk_monthly_budget_year_month",
        "adk_monthly_budget",
        ["year_month"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_adk_monthly_budget_year_month", table_name="adk_monthly_budget")
    op.drop_table("adk_monthly_budget")
    op.drop_index("ix_adk_model_usage_logs_task_id", table_name="adk_model_usage_logs")
    op.drop_table("adk_model_usage_logs")
