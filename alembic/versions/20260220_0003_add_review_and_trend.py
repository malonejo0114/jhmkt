"""add review workflow and trend snapshots

Revision ID: 20260220_0003
Revises: 20260220_0002
Create Date: 2026-02-20 03:40:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260220_0003"
down_revision: Union[str, None] = "20260220_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


review_status = sa.Enum("PENDING", "APPROVED", "REJECTED", name="review_status")


def upgrade() -> None:
    review_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "content_unit",
        sa.Column("review_status", review_status, nullable=False, server_default="PENDING"),
    )
    op.add_column("content_unit", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("content_unit", sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_content_unit_reviewed_by",
        "content_unit",
        "app_user",
        ["reviewed_by"],
        ["id"],
    )
    op.create_index("idx_content_unit_review", "content_unit", ["biz_date", "review_status"])

    op.create_table(
        "trend_keyword_snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("biz_date", sa.Date(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False, server_default="NAVER"),
        sa.Column("keyword", sa.String(length=120), nullable=False),
        sa.Column("group_name", sa.String(length=120), nullable=False),
        sa.Column("ratio", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("delta_ratio", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("biz_date", "provider", "keyword", name="uq_trend_keyword_snapshot"),
    )
    op.create_index("idx_trend_keyword_biz_date_rank", "trend_keyword_snapshot", ["biz_date", "rank"])


def downgrade() -> None:
    op.drop_index("idx_trend_keyword_biz_date_rank", table_name="trend_keyword_snapshot")
    op.drop_table("trend_keyword_snapshot")

    op.drop_index("idx_content_unit_review", table_name="content_unit")
    op.drop_constraint("fk_content_unit_reviewed_by", "content_unit", type_="foreignkey")
    op.drop_column("content_unit", "reviewed_by")
    op.drop_column("content_unit", "reviewed_at")
    op.drop_column("content_unit", "review_status")

    review_status.drop(op.get_bind(), checkfirst=True)
