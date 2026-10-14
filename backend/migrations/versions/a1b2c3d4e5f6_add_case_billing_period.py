"""add_case_billing_period

Revision ID: a1b2c3d4e5f6
Revises: 9c10b2f1d3e4
Create Date: 2026-10-14 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '9c10b2f1d3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cases', sa.Column('period_start', sa.DateTime(), nullable=True))
    op.add_column('cases', sa.Column('period_end', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('cases', 'period_end')
    op.drop_column('cases', 'period_start')
