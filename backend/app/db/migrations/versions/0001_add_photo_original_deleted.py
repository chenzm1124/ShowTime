"""add photos.original_deleted

用户下载精修图后再删除原图（用于前后对比），需要标记原图是否已清理。

Revision ID: 0001_add_photo_original_deleted
Revises:
Create Date: 2026-07-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001_add_photo_original_deleted"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "photos",
        sa.Column(
            "original_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="原图是否已删除（下载精修图后清理）",
        ),
    )


def downgrade() -> None:
    op.drop_column("photos", "original_deleted")
