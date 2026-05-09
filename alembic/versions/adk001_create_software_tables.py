"""create software tables (AutoNoGaDa)

Revision ID: adk001_create_software
Revises:
Create Date: 2026-05-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "adk001_create_software"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SOFTWARE_TASK_STATUS_NAME = "softwaretaskstatus"

_VALUES = ("pending", "running", "completed", "failed")


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*_VALUES, name=SOFTWARE_TASK_STATUS_NAME).create(
        bind,
        checkfirst=True,
    )
    status_col = postgresql.ENUM(
        *_VALUES,
        name=SOFTWARE_TASK_STATUS_NAME,
        create_type=False,
    )

    op.create_table(
        "software_code_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("status", status_col, nullable=False),
        sa.Column("output_code", sa.Text(), nullable=True),
        sa.Column("ontology_passed", sa.Boolean(), nullable=True),
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
    )

    op.create_table(
        "software_task_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("model_used", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["software_code_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "software_task_fixes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("patch_body", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["software_code_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("software_task_fixes")
    op.drop_table("software_task_reviews")
    op.drop_table("software_code_tasks")
    postgresql.ENUM(name=SOFTWARE_TASK_STATUS_NAME).drop(
        op.get_bind(),
        checkfirst=True,
    )
