"""adk006 — SaaS billing: plans + subscriptions + usage records + monthly user usage.

Phase 2 비즈니스 트랙 (B-1). 한장요약 §"AutoNoGaDa ADK 가격 모델" 의 3-tier
($29/$99/$499) + Free 를 자체적으로 관리한다. 결제 게이트웨이는 B-7 백로그.

Upgrade 후 4개 Plan (free/dev/team/ent) 을 시드한다. 다운그레이드는 4개
테이블 모두 drop.
"""
from typing import Sequence, Union
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op


revision: str = "adk006_billing"
down_revision: Union[str, None] = "adk005_cost_tracking"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "billing_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("price_usd_per_month", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("monthly_call_quota", sa.Integer(), nullable=True),
        sa.Column("allowed_models", sa.String(length=128), nullable=False, server_default="FAST"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_billing_plans_code"),
    )
    op.create_index("ix_billing_plans_code", "billing_plans", ["code"], unique=True)

    op.create_table(
        "billing_subscriptions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="active"
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["billing_plans.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_billing_subscriptions_user_id", "billing_subscriptions", ["user_id"]
    )
    op.create_index(
        "ix_billing_subscriptions_status", "billing_subscriptions", ["status"]
    )

    op.create_table(
        "billing_usage_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("plan_code", sa.String(length=32), nullable=False),
        sa.Column(
            "tokens_estimated", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("model_used", sa.String(length=128), nullable=True),
        sa.Column(
            "success", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_billing_usage_records_user_id", "billing_usage_records", ["user_id"]
    )
    op.create_index(
        "ix_billing_usage_records_action", "billing_usage_records", ["action"]
    )
    op.create_index(
        "ix_billing_usage_records_created_at",
        "billing_usage_records",
        ["created_at"],
    )

    op.create_table(
        "billing_monthly_user_usage",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("year_month", sa.String(length=7), nullable=False),
        sa.Column(
            "calls_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "tokens_total", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("cost_usd", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column(
            "last_updated",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "year_month", name="uq_billing_monthly_user_year_month"
        ),
    )
    op.create_index(
        "ix_billing_monthly_user_usage_user_id",
        "billing_monthly_user_usage",
        ["user_id"],
    )
    op.create_index(
        "ix_billing_monthly_user_usage_year_month",
        "billing_monthly_user_usage",
        ["year_month"],
    )

    # Plan 4종 시드 — Free / Dev / Team / Ent (한장요약 §"AutoNoGaDa ADK 가격 모델")
    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    seed_plans = [
        {
            "id": "plan-free",
            "code": "free",
            "name": "Free",
            "price_usd_per_month": 0,
            "monthly_call_quota": 100,
            "allowed_models": "FAST",
            "description": "회원가입 즉시 체험 — 월 100회, FAST 모델 (LOCAL_FAST/gemma-4-e4b)",
        },
        {
            "id": "plan-dev",
            "code": "dev",
            "name": "Developer",
            "price_usd_per_month": 29,
            "monthly_call_quota": 1000,
            "allowed_models": "FAST",
            "description": "개인 개발자 — 월 1,000회, FAST 모델",
        },
        {
            "id": "plan-team",
            "code": "team",
            "name": "Team",
            "price_usd_per_month": 99,
            "monthly_call_quota": 10000,
            "allowed_models": "FAST,HEAVY",
            "description": "소규모 팀 — 월 10,000회, FAST+HEAVY 모델",
        },
        {
            "id": "plan-ent",
            "code": "ent",
            "name": "Enterprise",
            "price_usd_per_month": 499,
            "monthly_call_quota": None,
            "allowed_models": "FAST,HEAVY,CONSENSUS",
            "description": "엔터프라이즈 — 무제한, 전체 모델 (CONSENSUS 포함), SLA 99.9%",
        },
    ]
    for p in seed_plans:
        bind.execute(
            sa.text(
                "INSERT INTO billing_plans "
                "(id, code, name, price_usd_per_month, monthly_call_quota, "
                " allowed_models, description, is_active, created_at, updated_at) "
                "VALUES (:id, :code, :name, :price, :quota, :models, :desc, "
                "        true, :now, :now)"
            ),
            {
                "id": p["id"],
                "code": p["code"],
                "name": p["name"],
                "price": p["price_usd_per_month"],
                "quota": p["monthly_call_quota"],
                "models": p["allowed_models"],
                "desc": p["description"],
                "now": now,
            },
        )


def downgrade() -> None:
    op.drop_index(
        "ix_billing_monthly_user_usage_year_month",
        table_name="billing_monthly_user_usage",
    )
    op.drop_index(
        "ix_billing_monthly_user_usage_user_id",
        table_name="billing_monthly_user_usage",
    )
    op.drop_table("billing_monthly_user_usage")

    op.drop_index(
        "ix_billing_usage_records_created_at", table_name="billing_usage_records"
    )
    op.drop_index(
        "ix_billing_usage_records_action", table_name="billing_usage_records"
    )
    op.drop_index(
        "ix_billing_usage_records_user_id", table_name="billing_usage_records"
    )
    op.drop_table("billing_usage_records")

    op.drop_index(
        "ix_billing_subscriptions_status", table_name="billing_subscriptions"
    )
    op.drop_index(
        "ix_billing_subscriptions_user_id", table_name="billing_subscriptions"
    )
    op.drop_table("billing_subscriptions")

    op.drop_index("ix_billing_plans_code", table_name="billing_plans")
    op.drop_table("billing_plans")
