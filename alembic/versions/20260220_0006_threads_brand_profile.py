"""add brand_profile_id to threads_account

Revision ID: 20260220_0006
Revises: 20260220_0005
Create Date: 2026-02-25 23:58:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260220_0006"
down_revision: Union[str, None] = "20260220_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "threads_account",
        sa.Column("brand_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_threads_account_brand_profile",
        "threads_account",
        "brand_profile",
        ["brand_profile_id"],
        ["id"],
    )
    op.create_index(
        "idx_threads_account_brand_profile",
        "threads_account",
        ["brand_profile_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_threads_account_brand_profile", table_name="threads_account")
    op.drop_constraint("fk_threads_account_brand_profile", "threads_account", type_="foreignkey")
    op.drop_column("threads_account", "brand_profile_id")
