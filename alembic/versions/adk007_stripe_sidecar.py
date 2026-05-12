"""adk007 — Stripe sidecar 테이블 2종 (B-7, 2026-05-12).

기존 ``billing_plans`` / ``billing_subscriptions`` 무변경 — sidecar 1:1 매핑:
    - ``stripe_plan_mappings`` (plan_id ↔ stripe_price_id)
    - ``stripe_subscriptions`` (subscription_id ↔ stripe_customer/subscription)

운영 토글: 환경변수 ``STRIPE_ENABLED=0`` 기본. 본 마이그레이션은 토글 무관 (스키마만).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "adk007_stripe_sidecar"
down_revision: Union[str, None] = "adk006_billing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stripe_plan_mappings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("stripe_price_id", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["billing_plans.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", name="uq_stripe_plan_mappings_plan_id"),
        sa.UniqueConstraint(
            "stripe_price_id",
            name="uq_stripe_plan_mappings_stripe_price_id",
        ),
    )
    op.create_index(
        "ix_stripe_plan_mappings_plan_id",
        "stripe_plan_mappings", ["plan_id"],
    )
    op.create_index(
        "ix_stripe_plan_mappings_stripe_price_id",
        "stripe_plan_mappings", ["stripe_price_id"],
    )

    op.create_table(
        "stripe_subscriptions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subscription_id", sa.String(length=36), nullable=False),
        sa.Column(
            "stripe_customer_id", sa.String(length=128), nullable=False
        ),
        sa.Column(
            "stripe_subscription_id", sa.String(length=128), nullable=False
        ),
        sa.Column(
            "stripe_status", sa.String(length=32), nullable=False,
            server_default="incomplete",
        ),
        sa.Column(
            "current_period_end", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "cancel_at_period_end", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["billing_subscriptions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subscription_id", name="uq_stripe_subscriptions_subscription_id"
        ),
        sa.UniqueConstraint(
            "stripe_subscription_id",
            name="uq_stripe_subscriptions_stripe_subscription_id",
        ),
    )
    op.create_index(
        "ix_stripe_subscriptions_subscription_id",
        "stripe_subscriptions", ["subscription_id"],
    )
    op.create_index(
        "ix_stripe_subscriptions_stripe_customer_id",
        "stripe_subscriptions", ["stripe_customer_id"],
    )
    op.create_index(
        "ix_stripe_subscriptions_stripe_subscription_id",
        "stripe_subscriptions", ["stripe_subscription_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_stripe_subscriptions_stripe_subscription_id",
        table_name="stripe_subscriptions",
    )
    op.drop_index(
        "ix_stripe_subscriptions_stripe_customer_id",
        table_name="stripe_subscriptions",
    )
    op.drop_index(
        "ix_stripe_subscriptions_subscription_id",
        table_name="stripe_subscriptions",
    )
    op.drop_table("stripe_subscriptions")
    op.drop_index(
        "ix_stripe_plan_mappings_stripe_price_id",
        table_name="stripe_plan_mappings",
    )
    op.drop_index(
        "ix_stripe_plan_mappings_plan_id",
        table_name="stripe_plan_mappings",
    )
    op.drop_table("stripe_plan_mappings")
