"""add account scope columns to content_unit

Revision ID: 20260220_0007
Revises: 20260220_0006
Create Date: 2026-02-26 01:35:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260220_0007"
down_revision = "20260220_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_unit",
        sa.Column("threads_account_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "content_unit",
        sa.Column("instagram_account_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_content_unit_threads_account_id",
        "content_unit",
        "threads_account",
        ["threads_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_content_unit_instagram_account_id",
        "content_unit",
        "instagram_account",
        ["instagram_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_content_unit_threads_account_id",
        "content_unit",
        ["threads_account_id"],
        unique=False,
    )
    op.create_index(
        "idx_content_unit_instagram_account_id",
        "content_unit",
        ["instagram_account_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_content_unit_instagram_account_id", table_name="content_unit")
    op.drop_index("idx_content_unit_threads_account_id", table_name="content_unit")
    op.drop_constraint("fk_content_unit_instagram_account_id", "content_unit", type_="foreignkey")
    op.drop_constraint("fk_content_unit_threads_account_id", "content_unit", type_="foreignkey")
    op.drop_column("content_unit", "instagram_account_id")
    op.drop_column("content_unit", "threads_account_id")

