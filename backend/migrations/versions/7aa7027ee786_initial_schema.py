"""initial_schema

Revision ID: 7aa7027ee786
Revises: 
Create Date: 2026-10-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg


# revision identifiers, used by Alembic.
revision: str = '7aa7027ee786'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ensure_enum_created(bind, name, values):
    if bind.dialect.name == "postgresql":
        vals = ", ".join(f"'{v}'" for v in values)
        bind.execute(sa.text(f"""
            DO $$ BEGIN
                CREATE TYPE {name} AS ENUM ({vals});
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """))


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # 1. Safely ensure all PostgreSQL ENUM types exist without duplicate errors
    _ensure_enum_created(bind, 'case_status_enum', ['OPEN', 'AWAITING_INFO', 'RESOLVED', 'REOPENED'])
    _ensure_enum_created(bind, 'engine_status_enum', ['OK', 'AMBIGUOUS', 'INSUFFICIENT_DATA', 'PARTIAL'])
    _ensure_enum_created(bind, 'finding_type_db_enum', ['CONFIRMED_CALCULATION_DISCREPANCY', 'NO_DISCREPANCY', 'AMBIGUOUS', 'INSUFFICIENT_DATA'])
    _ensure_enum_created(bind, 'rule_type_enum', ['FLAT', 'PER_UNIT', 'TIERED_GRADUATED', 'TIERED_VOLUME', 'INCLUDED_UNITS', 'DISCOUNT_PCT', 'MINIMUM_COMMIT'])
    _ensure_enum_created(bind, 'run_status_enum', ['RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED', 'BLOCKED', 'DISCARDED'])
    _ensure_enum_created(bind, 'agent_finding_type_enum', ['CONFIRMED_CALCULATION_DISCREPANCY', 'POSSIBLE_DISCREPANCY', 'CONTRACT_AMBIGUITY', 'INSUFFICIENT_EVIDENCE', 'NO_DISCREPANCY', 'UNRESOLVED'])
    _ensure_enum_created(bind, 'option_type_enum', ['REQUEST_EVIDENCE', 'ESCALATE', 'CORRECT_INVOICE', 'RECOMMEND_CREDIT', 'CLOSE_NO_ADJUSTMENT', 'CREDIT_UNDISPUTED_PORTION'])
    _ensure_enum_created(bind, 'review_decision_enum', ['ACCEPT', 'EDIT', 'REJECT'])

    # Explicit postgresql.ENUM types with create_type=False so op.create_table never double-creates types
    case_status_enum = pg.ENUM('OPEN', 'AWAITING_INFO', 'RESOLVED', 'REOPENED', name='case_status_enum', create_type=False)
    engine_status_enum = pg.ENUM('OK', 'AMBIGUOUS', 'INSUFFICIENT_DATA', 'PARTIAL', name='engine_status_enum', create_type=False)
    finding_type_db_enum = pg.ENUM('CONFIRMED_CALCULATION_DISCREPANCY', 'NO_DISCREPANCY', 'AMBIGUOUS', 'INSUFFICIENT_DATA', name='finding_type_db_enum', create_type=False)
    rule_type_enum = pg.ENUM('FLAT', 'PER_UNIT', 'TIERED_GRADUATED', 'TIERED_VOLUME', 'INCLUDED_UNITS', 'DISCOUNT_PCT', 'MINIMUM_COMMIT', name='rule_type_enum', create_type=False)
    run_status_enum = pg.ENUM('RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED', 'BLOCKED', 'DISCARDED', name='run_status_enum', create_type=False)
    agent_finding_type_enum = pg.ENUM('CONFIRMED_CALCULATION_DISCREPANCY', 'POSSIBLE_DISCREPANCY', 'CONTRACT_AMBIGUITY', 'INSUFFICIENT_EVIDENCE', 'NO_DISCREPANCY', 'UNRESOLVED', name='agent_finding_type_enum', create_type=False)
    option_type_enum = pg.ENUM('REQUEST_EVIDENCE', 'ESCALATE', 'CORRECT_INVOICE', 'RECOMMEND_CREDIT', 'CLOSE_NO_ADJUSTMENT', 'CREDIT_UNDISPUTED_PORTION', name='option_type_enum', create_type=False)
    review_decision_enum = pg.ENUM('ACCEPT', 'EDIT', 'REJECT', name='review_decision_enum', create_type=False)

    insp = sa.inspect(bind)
    if insp.has_table('cases'):
        # Existing database sync: add any columns that may be missing on existing deployments
        if is_pg:
            bind.execute(sa.text("ALTER TYPE option_type_enum ADD VALUE IF NOT EXISTS 'CREDIT_UNDISPUTED_PORTION'"))

        def add_col_if_missing(table, col_name, col_type_sql):
            cols = [c["name"] for c in insp.get_columns(table)] if insp.has_table(table) else []
            if col_name not in cols:
                bind.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type_sql}"))

        add_col_if_missing("calculations", "quarantined_events", "JSON")
        add_col_if_missing("calculation_line_results", "quarantined_events", "JSON")
        add_col_if_missing("calculation_line_results", "undisputed_overcharge_cents", "INTEGER")
        add_col_if_missing("contract_rules", "is_active", "BOOLEAN DEFAULT TRUE")
        add_col_if_missing("contract_rules", "supersedes_rule_id", "VARCHAR(36)")
        add_col_if_missing("cases", "period_start", "TIMESTAMP")
        add_col_if_missing("cases", "period_end", "TIMESTAMP")
        add_col_if_missing("cases", "invoice_id", "VARCHAR(64)")
        add_col_if_missing("cases", "currency", "VARCHAR(10) DEFAULT 'USD'")
        add_col_if_missing("cases", "claimed_usage_quantity", "NUMERIC(20, 6)")
        add_col_if_missing("cases", "claimed_usage_uom", "VARCHAR(50)")
        add_col_if_missing("findings", "narrative", "TEXT")
        add_col_if_missing("findings", "validation_notes", "JSON")
        add_col_if_missing("findings", "invoice_line_id", "VARCHAR(36)")
        add_col_if_missing("resolution_options", "invoice_line_id", "VARCHAR(36)")
        add_col_if_missing("credits", "finding_id", "VARCHAR(36)")
        return

    # Fresh database creation: create all 13 tables matching Base.metadata exactly
    op.create_table('cases',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('customer_name', sa.String(length=100), nullable=False),
        sa.Column('invoice_id', sa.String(length=64), nullable=True),
        sa.Column('currency', sa.String(length=10), nullable=False, server_default='USD'),
        sa.Column('claimed_usage_quantity', sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column('claimed_usage_uom', sa.String(length=50), nullable=True),
        sa.Column('disputed_amount_cents', sa.Integer(), nullable=False),
        sa.Column('dispute_description', sa.Text(), nullable=True),
        sa.Column('status', case_status_enum, nullable=False),
        sa.Column('evidence_version', sa.Integer(), nullable=False),
        sa.Column('period_start', sa.DateTime(), nullable=True),
        sa.Column('period_end', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('calculations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('case_id', sa.String(length=36), nullable=False),
        sa.Column('evidence_version', sa.Integer(), nullable=False),
        sa.Column('engine_status', engine_status_enum, nullable=False),
        sa.Column('engine_status_reason', sa.Text(), nullable=True),
        sa.Column('total_original_billed_cents', sa.Integer(), nullable=False),
        sa.Column('total_recalculated_cents', sa.Integer(), nullable=True),
        sa.Column('total_difference_cents', sa.Integer(), nullable=True),
        sa.Column('result_hash', sa.String(length=64), nullable=False),
        sa.Column('quarantined_events', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_calculations_case_id'), 'calculations', ['case_id'], unique=False)

    op.create_table('case_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('case_id', sa.String(length=36), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('actor', sa.String(length=50), nullable=False),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('correlation_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_case_events_case_id'), 'case_events', ['case_id'], unique=False)
    op.create_index(op.f('ix_case_events_correlation_id'), 'case_events', ['correlation_id'], unique=False)
    op.create_index(op.f('ix_case_events_event_type'), 'case_events', ['event_type'], unique=False)

    op.create_table('evidence_versions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('case_id', sa.String(length=36), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('created_by', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('case_id', 'version_number', name='uq_evidence_versions_case_version')
    )
    op.create_index(op.f('ix_evidence_versions_case_id'), 'evidence_versions', ['case_id'], unique=False)

    op.create_table('invoice_lines',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('case_id', sa.String(length=36), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=False),
        sa.Column('original_amount_cents', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', 'case_id')
    )
    op.create_index(op.f('ix_invoice_lines_case_id'), 'invoice_lines', ['case_id'], unique=False)

    op.create_table('adjustments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('case_id', sa.String(length=36), nullable=False),
        sa.Column('invoice_line_id', sa.String(length=36), nullable=True),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('is_verified', sa.Boolean(), nullable=False),
        sa.Column('evidence_source', sa.String(length=255), nullable=True),
        sa.Column('applied_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['case_id', 'invoice_line_id'], ['invoice_lines.case_id', 'invoice_lines.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', 'case_id')
    )
    op.create_index(op.f('ix_adjustments_case_id'), 'adjustments', ['case_id'], unique=False)
    op.create_index(op.f('ix_adjustments_invoice_line_id'), 'adjustments', ['invoice_line_id'], unique=False)

    op.create_table('calculation_line_results',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('calculation_id', sa.String(length=36), nullable=False),
        sa.Column('line_id', sa.String(length=36), nullable=False),
        sa.Column('result_id', sa.String(length=40), nullable=False),
        sa.Column('rule_id', sa.String(length=36), nullable=False),
        sa.Column('original_amount_cents', sa.Integer(), nullable=False),
        sa.Column('recalculated_amount_cents', sa.Integer(), nullable=True),
        sa.Column('difference_cents', sa.Integer(), nullable=True),
        sa.Column('finding_type', finding_type_db_enum, nullable=False),
        sa.Column('quantity_used', sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column('exempt_quantity', sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column('applied_discount_pct', sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column('applied_minimum_commit_cents', sa.Integer(), nullable=False),
        sa.Column('interpretations', sa.JSON(), nullable=True),
        sa.Column('assumptions', sa.JSON(), nullable=True),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('quarantined_events', sa.JSON(), nullable=True),
        sa.Column('undisputed_overcharge_cents', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['calculation_id'], ['calculations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_calculation_line_results_calculation_id'), 'calculation_line_results', ['calculation_id'], unique=False)
    op.create_index(op.f('ix_calculation_line_results_line_id'), 'calculation_line_results', ['line_id'], unique=False)
    op.create_index(op.f('ix_calculation_line_results_result_id'), 'calculation_line_results', ['result_id'], unique=False)

    op.create_table('contract_rules',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('case_id', sa.String(length=36), nullable=False),
        sa.Column('line_id', sa.String(length=36), nullable=False),
        sa.Column('rule_type', rule_type_enum, nullable=False),
        sa.Column('rate_cents', sa.Integer(), nullable=False),
        sa.Column('tiers', sa.JSON(), nullable=True),
        sa.Column('discount_pct', sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column('minimum_commit_cents', sa.Integer(), nullable=False),
        sa.Column('included_units', sa.Integer(), nullable=False),
        sa.Column('overage_rate_cents', sa.Integer(), nullable=True),
        sa.Column('exempt_environments', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true' if is_pg else '1')),
        sa.Column('supersedes_rule_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['case_id', 'line_id'], ['invoice_lines.case_id', 'invoice_lines.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', 'case_id')
    )
    op.create_index(op.f('ix_contract_rules_case_id'), 'contract_rules', ['case_id'], unique=False)
    op.create_index(op.f('ix_contract_rules_line_id'), 'contract_rules', ['line_id'], unique=False)

    op.create_table('investigation_runs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('case_id', sa.String(length=36), nullable=False),
        sa.Column('calculation_id', sa.String(length=36), nullable=True),
        sa.Column('evidence_version', sa.Integer(), nullable=False),
        sa.Column('status', run_status_enum, nullable=False),
        sa.Column('status_reason', sa.Text(), nullable=True),
        sa.Column('token_usage', sa.JSON(), nullable=True),
        sa.Column('started_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['calculation_id'], ['calculations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_investigation_runs_case_id'), 'investigation_runs', ['case_id'], unique=False)
    op.create_index(
        'ix_one_running_investigation_per_case',
        'investigation_runs',
        ['case_id'],
        unique=True,
        postgresql_where=sa.text("status = 'RUNNING'"),
        sqlite_where=sa.text("status = 'RUNNING'"),
    )

    op.create_table('usage_events',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('case_id', sa.String(length=36), nullable=False),
        sa.Column('line_id', sa.String(length=36), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column('environment', sa.String(length=50), nullable=False),
        sa.Column('event_timestamp', sa.DateTime(), nullable=True),
        sa.Column('is_quarantined', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('quarantine_reason', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['case_id', 'line_id'], ['invoice_lines.case_id', 'invoice_lines.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', 'case_id')
    )
    op.create_index(op.f('ix_usage_events_case_id'), 'usage_events', ['case_id'], unique=False)
    op.create_index(op.f('ix_usage_events_line_id'), 'usage_events', ['line_id'], unique=False)

    op.create_table('findings',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=False),
        sa.Column('case_id', sa.String(length=36), nullable=False),
        sa.Column('invoice_line_id', sa.String(length=36), nullable=True),
        sa.Column('finding_type', agent_finding_type_enum, nullable=False),
        sa.Column('narrative', sa.Text(), nullable=True),
        sa.Column('raw_ai_text', sa.Text(), nullable=True),
        sa.Column('calculation_line_result_id', sa.Integer(), nullable=True),
        sa.Column('verified_facts', sa.JSON(), nullable=True),
        sa.Column('possible_explanations', sa.JSON(), nullable=True),
        sa.Column('assumptions', sa.JSON(), nullable=True),
        sa.Column('open_questions', sa.JSON(), nullable=True),
        sa.Column('missing_evidence_questions', sa.JSON(), nullable=True),
        sa.Column('citation_ids', sa.JSON(), nullable=True),
        sa.Column('citation_validation_passed', sa.Boolean(), nullable=False),
        sa.Column('consistency_check_passed', sa.Boolean(), nullable=False),
        sa.Column('validation_notes', sa.JSON(), nullable=True),
        sa.Column('is_stale', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('stale_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['calculation_line_result_id'], ['calculation_line_results.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['run_id'], ['investigation_runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_findings_case_id'), 'findings', ['case_id'], unique=False)
    op.create_index(op.f('ix_findings_invoice_line_id'), 'findings', ['invoice_line_id'], unique=False)
    op.create_index(op.f('ix_findings_run_id'), 'findings', ['run_id'], unique=False)

    op.create_table('resolution_options',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=False),
        sa.Column('case_id', sa.String(length=36), nullable=False),
        sa.Column('invoice_line_id', sa.String(length=36), nullable=True),
        sa.Column('option_type', option_type_enum, nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('calculation_line_result_id', sa.Integer(), nullable=True),
        sa.Column('is_stale', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('stale_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['calculation_line_result_id'], ['calculation_line_results.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['run_id'], ['investigation_runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_resolution_options_case_id'), 'resolution_options', ['case_id'], unique=False)
    op.create_index(op.f('ix_resolution_options_invoice_line_id'), 'resolution_options', ['invoice_line_id'], unique=False)
    op.create_index(op.f('ix_resolution_options_run_id'), 'resolution_options', ['run_id'], unique=False)

    op.create_table('credits',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('case_id', sa.String(length=36), nullable=False),
        sa.Column('invoice_line_id', sa.String(length=36), nullable=False),
        sa.Column('finding_id', sa.String(length=36), nullable=True),
        sa.Column('resolution_option_id', sa.String(length=36), nullable=True),
        sa.Column('calculation_line_result_id', sa.Integer(), nullable=True),
        sa.Column('idempotency_key', sa.String(length=64), nullable=False),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('reason_code', sa.String(length=50), nullable=False),
        sa.Column('reason_note', sa.Text(), nullable=True),
        sa.Column('approved_by', sa.String(length=50), nullable=False),
        sa.Column('approved_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.CheckConstraint('amount_cents > 0', name='check_credit_amount_positive'),
        sa.ForeignKeyConstraint(['calculation_line_result_id'], ['calculation_line_results.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['case_id', 'invoice_line_id'], ['invoice_lines.case_id', 'invoice_lines.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['finding_id'], ['findings.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['resolution_option_id'], ['resolution_options.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('finding_id', name='uq_credits_finding_id'),
        sa.UniqueConstraint('idempotency_key', name='uq_credits_idempotency_key')
    )
    op.create_index(op.f('ix_credits_case_id'), 'credits', ['case_id'], unique=False)
    op.create_index(op.f('ix_credits_finding_id'), 'credits', ['finding_id'], unique=False)
    op.create_index(op.f('ix_credits_invoice_line_id'), 'credits', ['invoice_line_id'], unique=False)

    op.create_table('finding_reviews',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('finding_id', sa.String(length=36), nullable=False),
        sa.Column('action', review_decision_enum, nullable=False),
        sa.Column('reviewer', sa.String(length=50), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('original_ai_text', sa.Text(), nullable=True),
        sa.Column('edited_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['finding_id'], ['findings.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_finding_reviews_finding_id'), 'finding_reviews', ['finding_id'], unique=False)


def downgrade() -> None:
    pass
