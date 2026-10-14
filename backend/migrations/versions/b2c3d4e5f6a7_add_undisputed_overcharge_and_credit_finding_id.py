"""add_undisputed_overcharge_and_credit_finding_id

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-14 19:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    calc_cols = [c['name'] for c in insp.get_columns('calculation_line_results')] if insp.has_table('calculation_line_results') else []
    credit_cols = [c['name'] for c in insp.get_columns('credits')] if insp.has_table('credits') else []

    with op.batch_alter_table('calculation_line_results') as batch_op:
        if 'undisputed_overcharge_cents' not in calc_cols:
            batch_op.add_column(sa.Column('undisputed_overcharge_cents', sa.Integer(), nullable=True))

    with op.batch_alter_table('credits') as batch_op:
        if 'finding_id' not in credit_cols:
            batch_op.add_column(sa.Column('finding_id', sa.String(length=36), nullable=True))
            try:
                batch_op.create_unique_constraint('uq_credits_finding_id', ['finding_id'])
            except Exception:
                pass


def downgrade() -> None:
    with op.batch_alter_table('credits') as batch_op:
        batch_op.drop_constraint('uq_credits_finding_id', type_='unique')
        batch_op.drop_column('finding_id')

    with op.batch_alter_table('calculation_line_results') as batch_op:
        batch_op.drop_column('undisputed_overcharge_cents')
