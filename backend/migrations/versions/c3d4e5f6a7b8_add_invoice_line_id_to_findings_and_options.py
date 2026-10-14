"""add_invoice_line_id_to_findings_and_options

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-15 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    case_cols = [c['name'] for c in insp.get_columns('cases')] if insp.has_table('cases') else []
    adj_cols = [c['name'] for c in insp.get_columns('adjustments')] if insp.has_table('adjustments') else []
    finding_cols = [c['name'] for c in insp.get_columns('findings')] if insp.has_table('findings') else []
    res_cols = [c['name'] for c in insp.get_columns('resolution_options')] if insp.has_table('resolution_options') else []

    with op.batch_alter_table('cases') as batch_op:
        if 'invoice_id' not in case_cols:
            batch_op.add_column(sa.Column('invoice_id', sa.String(length=64), nullable=True))
        if 'currency' not in case_cols:
            batch_op.add_column(sa.Column('currency', sa.String(length=10), server_default='USD', nullable=False))
        if 'claimed_usage_quantity' not in case_cols:
            batch_op.add_column(sa.Column('claimed_usage_quantity', sa.Numeric(precision=20, scale=6), nullable=True))
        if 'claimed_usage_uom' not in case_cols:
            batch_op.add_column(sa.Column('claimed_usage_uom', sa.String(length=50), nullable=True))

    with op.batch_alter_table('adjustments') as batch_op:
        if 'is_verified' not in adj_cols:
            batch_op.add_column(sa.Column('is_verified', sa.Boolean(), server_default='1', nullable=False))
        if 'evidence_source' not in adj_cols:
            batch_op.add_column(sa.Column('evidence_source', sa.String(length=255), nullable=True))

    with op.batch_alter_table('findings') as batch_op:
        if 'invoice_line_id' not in finding_cols:
            batch_op.add_column(sa.Column('invoice_line_id', sa.String(length=64), nullable=True))
            try:
                batch_op.create_index('ix_findings_invoice_line_id', ['invoice_line_id'], unique=False)
            except Exception:
                pass

    with op.batch_alter_table('resolution_options') as batch_op:
        if 'invoice_line_id' not in res_cols:
            batch_op.add_column(sa.Column('invoice_line_id', sa.String(length=64), nullable=True))
            try:
                batch_op.create_index('ix_resolution_options_invoice_line_id', ['invoice_line_id'], unique=False)
            except Exception:
                pass


def downgrade() -> None:
    with op.batch_alter_table('resolution_options') as batch_op:
        batch_op.drop_index('ix_resolution_options_invoice_line_id')
        batch_op.drop_column('invoice_line_id')

    with op.batch_alter_table('findings') as batch_op:
        batch_op.drop_index('ix_findings_invoice_line_id')
        batch_op.drop_column('invoice_line_id')

    with op.batch_alter_table('adjustments') as batch_op:
        batch_op.drop_column('evidence_source')
        batch_op.drop_column('is_verified')

    with op.batch_alter_table('cases') as batch_op:
        batch_op.drop_column('claimed_usage_uom')
        batch_op.drop_column('claimed_usage_quantity')
        batch_op.drop_column('currency')
        batch_op.drop_column('invoice_id')
