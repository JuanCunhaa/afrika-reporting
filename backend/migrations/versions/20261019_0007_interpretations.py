"""F08: interpretações de indicadores (texto editorial assistido) com revisão humana.

Garantias no próprio banco (gatilhos), além das regras da aplicação:
- versões de interpretação são imutáveis e nunca excluídas (edição/regeneração = nova versão encadeada ao pai);
- eventos de revisão (GENERATED, IN_REVIEW, APPROVED, REJECTED, APPLIED) e a desativação por slide são append-only;
  o estado vigente é o último evento.
Nenhuma tabela anterior é alterada: snapshots, aprovações e apresentações continuam intocados (o texto aprovado só
entra num slide por uma NOVA revisão da apresentação, pelo caminho normal da F06A).

Revision ID: 0007_interpretations
Revises: 0006_themes
Create Date: 2026-10-19
"""
from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0007_interpretations'
down_revision: str | None = '0006_themes'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DESTRUCTIVE_DOWNGRADE_VAR = 'AFRIKA_ALLOW_DESTRUCTIVE_DOWNGRADE'
TABLES = ('interpretation_versions', 'interpretation_events', 'interpretation_slide_settings')


def _append_only(table: str) -> dict[str, str]:
    return {
        f'trg_{table}_no_update': f"""
            CREATE TRIGGER trg_{table}_no_update BEFORE UPDATE ON {table}
            BEGIN SELECT RAISE(ABORT, '{table}_append_only'); END""",
        f'trg_{table}_no_delete': f"""
            CREATE TRIGGER trg_{table}_no_delete BEFORE DELETE ON {table}
            BEGIN SELECT RAISE(ABORT, '{table}_append_only'); END""",
    }


_TRIGGERS = {k: v for t in TABLES for k, v in _append_only(t).items()}


def upgrade() -> None:
    op.create_table(
        'interpretation_versions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('presentation_id', sa.Uuid(), nullable=False),
        sa.Column('owner_key', sa.String(80), nullable=False),
        sa.Column('client_id', sa.Uuid(), nullable=False),
        sa.Column('subclient_id', sa.Uuid(), nullable=True),
        sa.Column('competence_id', sa.Uuid(), nullable=False),
        sa.Column('competence', sa.String(7), nullable=False),
        sa.Column('presentation_revision', sa.Integer(), nullable=False),
        sa.Column('presentation_sources_hash', sa.String(64), nullable=False),
        sa.Column('slide_id', sa.String(40), nullable=False),
        sa.Column('target_field', sa.String(20), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False),
        sa.Column('level', sa.String(20), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('parent_id', sa.Uuid(), nullable=True),
        sa.Column('origin', sa.String(20), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('statements_json', sa.Text(), nullable=False),
        sa.Column('facts_json', sa.Text(), nullable=False),
        sa.Column('editorial_json', sa.Text(), nullable=False),
        sa.Column('provider', sa.String(60), nullable=False),
        sa.Column('model', sa.String(120), nullable=True),
        sa.Column('prompt_version', sa.String(40), nullable=False),
        sa.Column('prompt_hash', sa.String(64), nullable=False),
        sa.Column('context_hash', sa.String(64), nullable=False),
        sa.Column('validation_json', sa.Text(), nullable=False),
        sa.Column('valid', sa.Boolean(), nullable=False),
        sa.Column('justification', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(120), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.CheckConstraint('version >= 1', name='ck_interpretation_versions_version_positive'),
        sa.CheckConstraint("origin IN ('GENERATED', 'EDITED')", name='ck_interpretation_versions_origin'),
        sa.CheckConstraint("level IN ('EXECUTIVE', 'TECHNICAL')", name='ck_interpretation_versions_level'),
        sa.ForeignKeyConstraint(['presentation_id'], ['presentations.id'], ondelete='RESTRICT',
                                name='fk_interpretation_versions_presentation_id_presentations'),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='RESTRICT',
                                name='fk_interpretation_versions_client_id_clients'),
        sa.ForeignKeyConstraint(['subclient_id'], ['subclients.id'], ondelete='RESTRICT',
                                name='fk_interpretation_versions_subclient_id_subclients'),
        sa.ForeignKeyConstraint(['competence_id'], ['competences.id'], ondelete='RESTRICT',
                                name='fk_interpretation_versions_competence_id_competences'),
        sa.ForeignKeyConstraint(['parent_id'], ['interpretation_versions.id'], ondelete='RESTRICT',
                                name='fk_interpretation_versions_parent_id_interpretation_versions'),
        sa.PrimaryKeyConstraint('id', name='pk_interpretation_versions'),
        sa.UniqueConstraint('presentation_id', 'slide_id', 'kind', 'version',
                            name='uq_interpretation_versions_presentation_id'),
    )
    op.create_index('ix_interpretation_versions_presentation_id', 'interpretation_versions', ['presentation_id'])
    op.create_index('ix_interpretation_versions_owner_key', 'interpretation_versions', ['owner_key'])

    op.create_table(
        'interpretation_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('interpretation_id', sa.Uuid(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('event', sa.String(20), nullable=False),
        sa.Column('actor', sa.String(120), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('presentation_revision', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('sequence >= 1', name='ck_interpretation_events_sequence_positive'),
        sa.CheckConstraint("event IN ('GENERATED', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'APPLIED')",
                           name='ck_interpretation_events_event'),
        sa.ForeignKeyConstraint(['interpretation_id'], ['interpretation_versions.id'], ondelete='RESTRICT',
                                name='fk_interpretation_events_interpretation_id_interpretation_versions'),
        sa.PrimaryKeyConstraint('id', name='pk_interpretation_events'),
        sa.UniqueConstraint('interpretation_id', 'sequence', name='uq_interpretation_events_interpretation_id'),
    )

    op.create_table(
        'interpretation_slide_settings',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('presentation_id', sa.Uuid(), nullable=False),
        sa.Column('slide_id', sa.String(40), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('disabled', sa.Boolean(), nullable=False),
        sa.Column('actor', sa.String(120), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('sequence >= 1', name='ck_interpretation_slide_settings_sequence_positive'),
        sa.ForeignKeyConstraint(['presentation_id'], ['presentations.id'], ondelete='RESTRICT',
                                name='fk_interpretation_slide_settings_presentation_id_presentations'),
        sa.PrimaryKeyConstraint('id', name='pk_interpretation_slide_settings'),
        sa.UniqueConstraint('presentation_id', 'slide_id', 'sequence',
                            name='uq_interpretation_slide_settings_presentation_id'),
    )
    for ddl in _TRIGGERS.values():
        op.execute(ddl)


def downgrade() -> None:
    # Histórico de revisão humana não é apagado por engano: exige confirmação explícita (procedimento administrativo).
    bind = op.get_bind()
    count = bind.execute(sa.text('SELECT COUNT(*) FROM interpretation_versions')).scalar()
    if count and os.getenv(DESTRUCTIVE_DOWNGRADE_VAR) != '1':
        raise RuntimeError(f'Downgrade recusado: {count} versão(ões) de interpretação seriam apagadas. '
                           f'Defina {DESTRUCTIVE_DOWNGRADE_VAR}=1 para confirmar.')
    for name in _TRIGGERS:
        op.execute(f'DROP TRIGGER IF EXISTS {name}')
    for table in reversed(TABLES):
        op.drop_table(table)
