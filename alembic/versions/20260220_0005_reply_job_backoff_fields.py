"""add backoff field for reply_job

Revision ID: 20260220_0005
Revises: 20260220_0004
Create Date: 2026-02-25 22:10:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260220_0005"
down_revision: Union[str, None] = "20260220_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reply_job", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "idx_reply_job_status_next_retry",
        "reply_job",
        ["status", "next_retry_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_reply_job_status_next_retry", table_name="reply_job")
    op.drop_column("reply_job", "next_retry_at")
