"""F05: competências, revisões, snapshots de indicadores, alterações manuais, aprovações e auditoria.

Garantias no próprio banco (gatilhos), além das regras da aplicação:
- revisão nasce DRAFT; transições só DRAFT -> READY_FOR_REVIEW -> APPROVED (e READY_FOR_REVIEW -> DRAFT);
- revisão APPROVED é imutável; nenhuma revisão é excluída;
- snapshots só mudam em revisão DRAFT; nenhum snapshot é excluído;
- execuções importadas, alterações manuais, aprovações e eventos de auditoria são append-only;
- aprovação só é registrada para revisão já marcada APPROVED da mesma competência.
`v_official_revisions` = referência da série histórica: a aprovação mais recente de cada competência.

Revision ID: 0004_snapshots
Revises: 0003_client_timezone
Create Date: 2026-10-15
"""
from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0004_snapshots'
down_revision: str | None = '0003_client_timezone'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DESTRUCTIVE_DOWNGRADE_VAR = 'AFRIKA_ALLOW_DESTRUCTIVE_DOWNGRADE'
_TECH = "'VALIDATED', 'INCOMPLETE', 'UNAVAILABLE', 'UNSUPPORTED', 'FAILED'"
_ORIGINS = "'VERACODE', 'MANUAL'"


def _append_only(table: str) -> dict[str, str]:
    return {
        f'trg_{table}_no_update': f"""
            CREATE TRIGGER trg_{table}_no_update BEFORE UPDATE ON {table}
            BEGIN SELECT RAISE(ABORT, '{table}_append_only'); END""",
        f'trg_{table}_no_delete': f"""
            CREATE TRIGGER trg_{table}_no_delete BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, '{table}_append_only'); END""",
    }


_TRIGGERS = {
    **_append_only('collection_runs'),
    **_append_only('manual_changes'),
    **_append_only('approvals'),
    **_append_only('audit_events'),
    'trg_competence_revisions_insert_draft': """
        CREATE TRIGGER trg_competence_revisions_insert_draft BEFORE INSERT ON competence_revisions
        WHEN NEW.status <> 'DRAFT'
        BEGIN SELECT RAISE(ABORT, 'revision_must_start_as_draft'); END""",
    'trg_competence_revisions_approved_immutable': """
        CREATE TRIGGER trg_competence_revisions_approved_immutable BEFORE UPDATE ON competence_revisions
        WHEN OLD.status = 'APPROVED'
        BEGIN SELECT RAISE(ABORT, 'revision_approved_immutable'); END""",
    'trg_competence_revisions_status_transition': """
        CREATE TRIGGER trg_competence_revisions_status_transition BEFORE UPDATE OF status ON competence_revisions
        WHEN NOT (OLD.status = NEW.status
                  OR (OLD.status = 'DRAFT' AND NEW.status = 'READY_FOR_REVIEW')
                  OR (OLD.status = 'READY_FOR_REVIEW' AND NEW.status IN ('DRAFT', 'APPROVED')))
        BEGIN SELECT RAISE(ABORT, 'revision_status_transition'); END""",
    'trg_competence_revisions_identity': """
        CREATE TRIGGER trg_competence_revisions_identity
        BEFORE UPDATE OF id, competence_id, number, base_revision_id, created_by, created_at ON competence_revisions
        WHEN NEW.id <> OLD.id OR NEW.competence_id <> OLD.competence_id OR NEW.number <> OLD.number
             OR NEW.base_revision_id IS NOT OLD.base_revision_id OR NEW.created_by <> OLD.created_by
             OR NEW.created_at <> OLD.created_at
        BEGIN SELECT RAISE(ABORT, 'revision_identity_immutable'); END""",
    'trg_competence_revisions_no_delete': """
        CREATE TRIGGER trg_competence_revisions_no_delete BEFORE DELETE ON competence_revisions
        BEGIN SELECT RAISE(ABORT, 'revision_delete_forbidden'); END""",
    'trg_competences_identity': """
        CREATE TRIGGER trg_competences_identity
        BEFORE UPDATE OF id, client_id, subclient_id, owner_key, label, timezone ON competences
        WHEN NEW.id <> OLD.id OR NEW.client_id <> OLD.client_id OR NEW.subclient_id IS NOT OLD.subclient_id
             OR NEW.owner_key <> OLD.owner_key OR NEW.label <> OLD.label OR NEW.timezone <> OLD.timezone
        BEGIN SELECT RAISE(ABORT, 'competence_identity_immutable'); END""",
    'trg_competences_no_delete': """
        CREATE TRIGGER trg_competences_no_delete BEFORE DELETE ON competences
        BEGIN SELECT RAISE(ABORT, 'competence_delete_forbidden'); END""",
    'trg_metric_snapshots_insert_draft': """
        CREATE TRIGGER trg_metric_snapshots_insert_draft BEFORE INSERT ON metric_snapshots
        WHEN (SELECT status FROM competence_revisions WHERE id = NEW.revision_id) IS NOT 'DRAFT'
        BEGIN SELECT RAISE(ABORT, 'snapshot_revision_not_draft'); END""",
    'trg_metric_snapshots_update_draft': """
        CREATE TRIGGER trg_metric_snapshots_update_draft BEFORE UPDATE ON metric_snapshots
        WHEN (SELECT status FROM competence_revisions WHERE id = OLD.revision_id) IS NOT 'DRAFT'
             OR NEW.revision_id <> OLD.revision_id OR NEW.metric_id <> OLD.metric_id
        BEGIN SELECT RAISE(ABORT, 'snapshot_revision_not_draft'); END""",
    'trg_metric_snapshots_no_delete': """
        CREATE TRIGGER trg_metric_snapshots_no_delete BEFORE DELETE ON metric_snapshots
        BEGIN SELECT RAISE(ABORT, 'snapshot_delete_forbidden'); END""",
    'trg_manual_changes_insert_draft': """
        CREATE TRIGGER trg_manual_changes_insert_draft BEFORE INSERT ON manual_changes
        WHEN (SELECT status FROM competence_revisions WHERE id = NEW.revision_id) IS NOT 'DRAFT'
        BEGIN SELECT RAISE(ABORT, 'manual_change_revision_not_draft'); END""",
    'trg_approvals_insert_approved': """
        CREATE TRIGGER trg_approvals_insert_approved BEFORE INSERT ON approvals
        WHEN (SELECT status FROM competence_revisions WHERE id = NEW.revision_id) IS NOT 'APPROVED'
             OR (SELECT competence_id FROM competence_revisions WHERE id = NEW.revision_id) IS NOT NEW.competence_id
        BEGIN SELECT RAISE(ABORT, 'approval_requires_approved_revision'); END""",
}

_VIEW = """
    CREATE VIEW v_official_revisions AS
    SELECT a.competence_id, a.revision_id, a.sequence, a.approved_at, a.content_hash, a.chain_hash
    FROM approvals a
    WHERE a.sequence = (SELECT MAX(b.sequence) FROM approvals b WHERE b.competence_id = a.competence_id)"""


def _owner_columns() -> list[sa.Column]:
    return [sa.Column('client_id', sa.Uuid(), nullable=False),
            sa.Column('subclient_id', sa.Uuid(), nullable=True),
            sa.Column('owner_key', sa.String(80), nullable=False)]


def upgrade() -> None:
    op.create_table(
        'collection_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        *_owner_columns(),
        sa.Column('competence_label', sa.String(7), nullable=False),
        sa.Column('timezone', sa.String(64), nullable=False),
        sa.Column('engine_version', sa.String(40), nullable=False),
        sa.Column('input_hash', sa.String(64), nullable=False),
        sa.Column('collected_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('scope_refs_json', sa.Text(), nullable=False),
        sa.Column('connection_json', sa.Text(), nullable=False),
        sa.Column('population_json', sa.Text(), nullable=False),
        sa.Column('collection_json', sa.Text(), nullable=False),
        sa.Column('summary_json', sa.Text(), nullable=False),
        sa.Column('imported_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('METRICS')", name='ck_collection_runs_kind'),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='RESTRICT',
                                name='fk_collection_runs_client_id_clients'),
        sa.ForeignKeyConstraint(['subclient_id'], ['subclients.id'], ondelete='RESTRICT',
                                name='fk_collection_runs_subclient_id_subclients'),
        sa.PrimaryKeyConstraint('id', name='pk_collection_runs'),
    )
    op.create_index('ix_collection_runs_client_id', 'collection_runs', ['client_id'])
    op.create_index('ix_collection_runs_subclient_id', 'collection_runs', ['subclient_id'])

    op.create_table(
        'competences',
        sa.Column('id', sa.Uuid(), nullable=False),
        *_owner_columns(),
        sa.Column('label', sa.String(7), nullable=False),
        sa.Column('timezone', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("label GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]'", name='ck_competences_label'),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='RESTRICT',
                                name='fk_competences_client_id_clients'),
        sa.ForeignKeyConstraint(['subclient_id'], ['subclients.id'], ondelete='RESTRICT',
                                name='fk_competences_subclient_id_subclients'),
        sa.PrimaryKeyConstraint('id', name='pk_competences'),
        sa.UniqueConstraint('owner_key', 'label', name='uq_competences_owner_key_label'),
    )
    op.create_index('ix_competences_client_id', 'competences', ['client_id'])
    op.create_index('ix_competences_subclient_id', 'competences', ['subclient_id'])

    op.create_table(
        'competence_revisions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('competence_id', sa.Uuid(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('base_revision_id', sa.Uuid(), nullable=True),
        sa.Column('lock_version', sa.Integer(), nullable=False),
        sa.Column('required_metrics_json', sa.Text(), nullable=False),
        sa.Column('required_set_version', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.String(120), nullable=False),
        sa.Column('submitted_by', sa.String(120), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT', 'READY_FOR_REVIEW', 'APPROVED')", name='ck_competence_revisions_status'),
        sa.CheckConstraint('number >= 1', name='ck_competence_revisions_number_positive'),
        sa.CheckConstraint('lock_version >= 1', name='ck_competence_revisions_lock_version_positive'),
        sa.ForeignKeyConstraint(['competence_id'], ['competences.id'], ondelete='RESTRICT',
                                name='fk_competence_revisions_competence_id_competences'),
        sa.ForeignKeyConstraint(['base_revision_id'], ['competence_revisions.id'], ondelete='RESTRICT',
                                name='fk_competence_revisions_base_revision_id_competence_revisions'),
        sa.PrimaryKeyConstraint('id', name='pk_competence_revisions'),
        sa.UniqueConstraint('competence_id', 'number', name='uq_competence_revisions_competence_id_number'),
    )
    op.create_index('uq_competence_revisions_one_open', 'competence_revisions', ['competence_id'], unique=True,
                    sqlite_where=sa.text("status IN ('DRAFT', 'READY_FOR_REVIEW')"))

    op.create_table(
        'metric_snapshots',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('revision_id', sa.Uuid(), nullable=False),
        sa.Column('metric_id', sa.String(80), nullable=False),
        sa.Column('contract_version', sa.Integer(), nullable=False),
        sa.Column('value_type', sa.String(20), nullable=False),
        sa.Column('shape', sa.String(20), nullable=False),
        sa.Column('unit', sa.String(40), nullable=False),
        sa.Column('origin', sa.String(10), nullable=False),
        sa.Column('value_json', sa.Text(), nullable=True),
        sa.Column('source_status', sa.String(20), nullable=True),
        sa.Column('source_value_json', sa.Text(), nullable=True),
        sa.Column('source_partial_json', sa.Text(), nullable=True),
        sa.Column('source_reasons_json', sa.Text(), nullable=False),
        sa.Column('dashboard_homologation', sa.String(32), nullable=False),
        sa.Column('source_name', sa.String(120), nullable=True),
        sa.Column('endpoint', sa.String(255), nullable=True),
        sa.Column('context', sa.String(24), nullable=True),
        sa.Column('collected_at', sa.DateTime(), nullable=True),
        sa.Column('temporal_json', sa.Text(), nullable=False),
        sa.Column('scope_refs_json', sa.Text(), nullable=False),
        sa.Column('provenance_json', sa.Text(), nullable=False),
        sa.Column('collection_run_id', sa.Uuid(), nullable=True),
        sa.Column('manual_justification', sa.Text(), nullable=True),
        sa.Column('manual_operator', sa.String(120), nullable=True),
        sa.Column('manual_at', sa.DateTime(), nullable=True),
        sa.Column('row_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(f'origin IN ({_ORIGINS})', name='ck_metric_snapshots_origin'),
        sa.CheckConstraint("value_type IN ('count', 'decimal', 'percentage', 'by_severity', 'breakdown', 'ranking')",
                           name='ck_metric_snapshots_value_type'),
        sa.CheckConstraint(f'source_status IS NULL OR source_status IN ({_TECH})',
                           name='ck_metric_snapshots_source_status'),
        sa.CheckConstraint("origin <> 'MANUAL' OR (value_json IS NOT NULL AND manual_justification IS NOT NULL "
                           "AND manual_operator IS NOT NULL AND manual_at IS NOT NULL)",
                           name='ck_metric_snapshots_manual_complete'),
        sa.CheckConstraint("origin <> 'VERACODE' OR value_json IS NULL OR source_status = 'VALIDATED'",
                           name='ck_metric_snapshots_veracode_value_validated'),
        sa.CheckConstraint("source_value_json IS NULL OR source_status = 'VALIDATED'",
                           name='ck_metric_snapshots_source_value_validated'),
        sa.ForeignKeyConstraint(['revision_id'], ['competence_revisions.id'], ondelete='RESTRICT',
                                name='fk_metric_snapshots_revision_id_competence_revisions'),
        sa.ForeignKeyConstraint(['collection_run_id'], ['collection_runs.id'], ondelete='RESTRICT',
                                name='fk_metric_snapshots_collection_run_id_collection_runs'),
        sa.PrimaryKeyConstraint('id', name='pk_metric_snapshots'),
        sa.UniqueConstraint('revision_id', 'metric_id', name='uq_metric_snapshots_revision_id_metric_id'),
    )
    op.create_index('ix_metric_snapshots_collection_run_id', 'metric_snapshots', ['collection_run_id'])

    op.create_table(
        'manual_changes',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('snapshot_id', sa.Uuid(), nullable=False),
        sa.Column('revision_id', sa.Uuid(), nullable=False),
        sa.Column('metric_id', sa.String(80), nullable=False),
        sa.Column('previous_value_json', sa.Text(), nullable=True),
        sa.Column('new_value_json', sa.Text(), nullable=True),
        sa.Column('previous_origin', sa.String(10), nullable=True),
        sa.Column('new_origin', sa.String(10), nullable=False),
        sa.Column('justification', sa.Text(), nullable=False),
        sa.Column('operator', sa.String(120), nullable=False),
        sa.Column('changed_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(f'previous_origin IS NULL OR previous_origin IN ({_ORIGINS})',
                           name='ck_manual_changes_previous_origin'),
        sa.CheckConstraint(f'new_origin IN ({_ORIGINS})', name='ck_manual_changes_new_origin'),
        sa.ForeignKeyConstraint(['snapshot_id'], ['metric_snapshots.id'], ondelete='RESTRICT',
                                name='fk_manual_changes_snapshot_id_metric_snapshots'),
        sa.ForeignKeyConstraint(['revision_id'], ['competence_revisions.id'], ondelete='RESTRICT',
                                name='fk_manual_changes_revision_id_competence_revisions'),
        sa.PrimaryKeyConstraint('id', name='pk_manual_changes'),
    )
    op.create_index('ix_manual_changes_snapshot_id', 'manual_changes', ['snapshot_id'])
    op.create_index('ix_manual_changes_revision_id', 'manual_changes', ['revision_id'])

    op.create_table(
        'approvals',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('competence_id', sa.Uuid(), nullable=False),
        sa.Column('revision_id', sa.Uuid(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('approver', sa.String(120), nullable=False),
        sa.Column('identity_mode', sa.String(40), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('previous_chain_hash', sa.String(64), nullable=True),
        sa.Column('chain_hash', sa.String(64), nullable=False),
        sa.CheckConstraint("identity_mode IN ('DECLARED_UNAUTHENTICATED')", name='ck_approvals_identity_mode'),
        sa.CheckConstraint('sequence >= 1', name='ck_approvals_sequence_positive'),
        sa.ForeignKeyConstraint(['competence_id'], ['competences.id'], ondelete='RESTRICT',
                                name='fk_approvals_competence_id_competences'),
        sa.ForeignKeyConstraint(['revision_id'], ['competence_revisions.id'], ondelete='RESTRICT',
                                name='fk_approvals_revision_id_competence_revisions'),
        sa.PrimaryKeyConstraint('id', name='pk_approvals'),
        sa.UniqueConstraint('revision_id', name='uq_approvals_revision_id'),
        sa.UniqueConstraint('competence_id', 'sequence', name='uq_approvals_competence_id_sequence'),
    )

    op.create_table(
        'audit_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('occurred_at', sa.DateTime(), nullable=False),
        sa.Column('event_type', sa.String(60), nullable=False),
        sa.Column('owner_key', sa.String(80), nullable=True),
        sa.Column('competence_id', sa.Uuid(), nullable=True),
        sa.Column('revision_id', sa.Uuid(), nullable=True),
        sa.Column('actor', sa.String(120), nullable=True),
        sa.Column('details_json', sa.Text(), nullable=False),
        sa.Column('prev_hash', sa.String(64), nullable=False),
        sa.Column('event_hash', sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(['competence_id'], ['competences.id'], ondelete='RESTRICT',
                                name='fk_audit_events_competence_id_competences'),
        sa.ForeignKeyConstraint(['revision_id'], ['competence_revisions.id'], ondelete='RESTRICT',
                                name='fk_audit_events_revision_id_competence_revisions'),
        sa.PrimaryKeyConstraint('id', name='pk_audit_events'),
        sa.UniqueConstraint('prev_hash', name='uq_audit_events_prev_hash'),
    )
    op.create_index('ix_audit_events_competence_id', 'audit_events', ['competence_id'])

    for ddl in _TRIGGERS.values():
        op.execute(ddl)
    op.execute(_VIEW)


def downgrade() -> None:
    # Histórico aprovado não é apagado por engano: com aprovações registradas, o downgrade exige confirmação
    # explícita do operador por variável de ambiente (procedimento administrativo, fora da aplicação).
    bind = op.get_bind()
    approvals = bind.execute(sa.text('SELECT COUNT(*) FROM approvals')).scalar()
    if approvals and os.getenv(DESTRUCTIVE_DOWNGRADE_VAR) != '1':
        raise RuntimeError(f'downgrade recusado: há {approvals} aprovação(ões) registradas; defina '
                           f'{DESTRUCTIVE_DOWNGRADE_VAR}=1 somente com backup e decisão explícita')
    op.execute('DROP VIEW IF EXISTS v_official_revisions')
    for name in _TRIGGERS:
        op.execute(f'DROP TRIGGER IF EXISTS {name}')
    op.drop_index('ix_audit_events_competence_id', table_name='audit_events')
    op.drop_table('audit_events')
    op.drop_table('approvals')
    op.drop_index('ix_manual_changes_revision_id', table_name='manual_changes')
    op.drop_index('ix_manual_changes_snapshot_id', table_name='manual_changes')
    op.drop_table('manual_changes')
    op.drop_index('ix_metric_snapshots_collection_run_id', table_name='metric_snapshots')
    op.drop_table('metric_snapshots')
    op.drop_index('uq_competence_revisions_one_open', table_name='competence_revisions')
    op.drop_table('competence_revisions')
    op.drop_index('ix_competences_subclient_id', table_name='competences')
    op.drop_index('ix_competences_client_id', table_name='competences')
    op.drop_table('competences')
    op.drop_index('ix_collection_runs_subclient_id', table_name='collection_runs')
    op.drop_index('ix_collection_runs_client_id', table_name='collection_runs')
    op.drop_table('collection_runs')
