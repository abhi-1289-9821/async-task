"""add_running_investigation_partial_index

Revision ID: 8b91a1e0c2f3
Revises: 7aa7027ee786
Create Date: 2026-10-14 17:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b91a1e0c2f3'
down_revision: Union[str, None] = '7aa7027ee786'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'ix_one_running_investigation_per_case',
        'investigation_runs',
        ['case_id'],
        unique=True,
        postgresql_where=sa.text("status = 'RUNNING'"),
        sqlite_where=sa.text("status = 'RUNNING'"),
    )


def downgrade() -> None:
    op.drop_index('ix_one_running_investigation_per_case', table_name='investigation_runs')
