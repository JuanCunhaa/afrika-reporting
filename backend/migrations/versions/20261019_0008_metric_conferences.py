"""F10: conferência humana dos indicadores com o valor oficial da plataforma Veracode.

Cada registro guarda, para UM indicador de UMA revisão de competência, o valor calculado (copiado do snapshot pelo
servidor, nunca enviado pelo cliente), o valor oficial informado pelo operador, as diferenças, o status
(MATCH / MISMATCH / NOT_COMPARABLE), a data da conferência e a evidência local declarada. Tabela APPEND-ONLY
(gatilhos): corrigir uma conferência = novo registro (sequence + 1); o vigente é o último.
Nenhuma tabela anterior é alterada: snapshots e aprovações continuam imutáveis (conferir não muda valor).

Revision ID: 0008_metric_conferences
Revises: 0007_interpretations
Create Date: 2026-10-19
"""
from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0008_metric_conferences'
down_revision: str | None = '0007_interpretations'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DESTRUCTIVE_DOWNGRADE_VAR = 'AFRIKA_ALLOW_DESTRUCTIVE_DOWNGRADE'
TABLE = 'metric_conferences'
_TRIGGERS = {
    f'trg_{TABLE}_no_update': f"""
        CREATE TRIGGER trg_{TABLE}_no_update BEFORE UPDATE ON {TABLE}
        BEGIN SELECT RAISE(ABORT, '{TABLE}_append_only'); END""",
    f'trg_{TABLE}_no_delete': f"""
        CREATE TRIGGER trg_{TABLE}_no_delete BEFORE DELETE ON {TABLE}
        BEGIN SELECT RAISE(ABORT, '{TABLE}_append_only'); END""",
}


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('competence_id', sa.Uuid(), nullable=False),
        sa.Column('revision_id', sa.Uuid(), nullable=False),
        sa.Column('owner_key', sa.String(80), nullable=False),
        sa.Column('metric_id', sa.String(80), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('snapshot_row_hash', sa.String(64), nullable=False),
        sa.Column('computed_origin', sa.String(10), nullable=False),
        sa.Column('entries_json', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('reasons_json', sa.Text(), nullable=False),
        sa.Column('filters_confirmed', sa.Boolean(), nullable=False),
        sa.Column('checked_on', sa.String(10), nullable=False),
        sa.Column('collected_on', sa.String(10), nullable=True),
        sa.Column('evidence', sa.Text(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('operator', sa.String(120), nullable=False),
        sa.Column('identity_mode', sa.String(40), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('record_hash', sa.String(64), nullable=False),
        sa.CheckConstraint('sequence >= 1', name='ck_metric_conferences_sequence_positive'),
        sa.CheckConstraint("status IN ('MATCH', 'MISMATCH', 'NOT_COMPARABLE')", name='ck_metric_conferences_status'),
        sa.CheckConstraint("identity_mode IN ('DECLARED_UNAUTHENTICATED')",
                           name='ck_metric_conferences_identity_mode'),
        sa.ForeignKeyConstraint(['competence_id'], ['competences.id'], ondelete='RESTRICT',
                                name='fk_metric_conferences_competence_id_competences'),
        sa.ForeignKeyConstraint(['revision_id'], ['competence_revisions.id'], ondelete='RESTRICT',
                                name='fk_metric_conferences_revision_id_competence_revisions'),
        sa.PrimaryKeyConstraint('id', name='pk_metric_conferences'),
        sa.UniqueConstraint('revision_id', 'metric_id', 'sequence', name='uq_metric_conferences_revision_id'),
    )
    op.create_index('ix_metric_conferences_revision_id', TABLE, ['revision_id'])
    for ddl in _TRIGGERS.values():
        op.execute(ddl)


def downgrade() -> None:
    # Evidência de conferência não é apagada por engano: exige confirmação explícita (procedimento administrativo).
    count = op.get_bind().execute(sa.text(f'SELECT COUNT(*) FROM {TABLE}')).scalar()
    if count and os.getenv(DESTRUCTIVE_DOWNGRADE_VAR) != '1':
        raise RuntimeError(f'Downgrade recusado: {count} conferência(s) seriam apagadas. '
                           f'Defina {DESTRUCTIVE_DOWNGRADE_VAR}=1 para confirmar.')
    for name in _TRIGGERS:
        op.execute(f'DROP TRIGGER IF EXISTS {name}')
    op.drop_index('ix_metric_conferences_revision_id', table_name=TABLE)
    op.drop_table(TABLE)
