"""add_contract_rule_superseding_and_active

Revision ID: 9c10b2f1d3e4
Revises: 8b91a1e0c2f3
Create Date: 2026-10-14 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c10b2f1d3e4'
down_revision: Union[str, None] = '8b91a1e0c2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c['name'] for c in insp.get_columns('contract_rules')] if insp.has_table('contract_rules') else []
    if 'is_active' not in cols:
        op.add_column('contract_rules', sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False))
    if 'supersedes_rule_id' not in cols:
        op.add_column('contract_rules', sa.Column('supersedes_rule_id', sa.String(length=36), nullable=True))


def downgrade() -> None:
    op.drop_column('contract_rules', 'supersedes_rule_id')
    op.drop_column('contract_rules', 'is_active')
