"""F06A: templates de apresentação versionados, escolha de template por dono, apresentações e revisões.

Garantias no próprio banco (gatilhos), além das regras da aplicação:
- versões de template são imutáveis e nunca excluídas (nova mudança = nova versão);
- escolhas de template por dono e revisões de apresentação são append-only;
- identidade da apresentação (dono, competência, template, autor) é imutável; nada é excluído;
- toda revisão de apresentação aponta para uma revisão de competência APROVADA e para a aprovação dessa revisão.
Nenhuma tabela desta migration altera snapshots/aprovações da F05 (o editor não tem caminho de escrita para eles).

Revision ID: 0005_presentations
Revises: 0004_snapshots
Create Date: 2026-10-15
"""
from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0005_presentations'
down_revision: str | None = '0004_snapshots'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DESTRUCTIVE_DOWNGRADE_VAR = 'AFRIKA_ALLOW_DESTRUCTIVE_DOWNGRADE'


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
    **_append_only('presentation_templates'),
    **_append_only('owner_template_selections'),
    **_append_only('presentation_revisions'),
    'trg_presentations_identity': """
        CREATE TRIGGER trg_presentations_identity
        BEFORE UPDATE OF id, owner_key, client_id, subclient_id, competence_id, template_id, created_by, created_at
        ON presentations
        WHEN NEW.id <> OLD.id OR NEW.owner_key <> OLD.owner_key OR NEW.client_id <> OLD.client_id
             OR NEW.subclient_id IS NOT OLD.subclient_id OR NEW.competence_id <> OLD.competence_id
             OR NEW.template_id <> OLD.template_id OR NEW.created_by <> OLD.created_by
             OR NEW.created_at <> OLD.created_at
        BEGIN SELECT RAISE(ABORT, 'presentation_identity_immutable'); END""",
    'trg_presentations_no_delete': """
        CREATE TRIGGER trg_presentations_no_delete BEFORE DELETE ON presentations
        BEGIN SELECT RAISE(ABORT, 'presentation_delete_forbidden'); END""",
    'trg_presentation_revisions_approved_source': """
        CREATE TRIGGER trg_presentation_revisions_approved_source BEFORE INSERT ON presentation_revisions
        WHEN (SELECT status FROM competence_revisions WHERE id = NEW.primary_revision_id) IS NOT 'APPROVED'
             OR (SELECT revision_id FROM approvals WHERE id = NEW.primary_approval_id) IS NOT NEW.primary_revision_id
        BEGIN SELECT RAISE(ABORT, 'presentation_source_not_approved'); END""",
}


def upgrade() -> None:
    op.create_table(
        'presentation_templates',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('template_key', sa.String(60), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('theme_id', sa.String(60), nullable=False),
        sa.Column('theme_version', sa.Integer(), nullable=False),
        sa.Column('origin', sa.String(10), nullable=False),
        sa.Column('definition_json', sa.Text(), nullable=False),
        sa.Column('definition_hash', sa.String(64), nullable=False),
        sa.Column('created_by', sa.String(120), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("origin IN ('BUILTIN', 'CUSTOM')", name='ck_presentation_templates_origin'),
        sa.CheckConstraint('version >= 1', name='ck_presentation_templates_version_positive'),
        sa.PrimaryKeyConstraint('id', name='pk_presentation_templates'),
        sa.UniqueConstraint('template_key', 'version', name='uq_presentation_templates_template_key_version'),
    )

    op.create_table(
        'owner_template_selections',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('owner_key', sa.String(80), nullable=False),
        sa.Column('client_id', sa.Uuid(), nullable=False),
        sa.Column('subclient_id', sa.Uuid(), nullable=True),
        sa.Column('template_id', sa.Uuid(), nullable=False),
        sa.Column('selected_by', sa.String(120), nullable=False),
        sa.Column('selected_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='RESTRICT',
                                name='fk_owner_template_selections_client_id_clients'),
        sa.ForeignKeyConstraint(['subclient_id'], ['subclients.id'], ondelete='RESTRICT',
                                name='fk_owner_template_selections_subclient_id_subclients'),
        sa.ForeignKeyConstraint(['template_id'], ['presentation_templates.id'], ondelete='RESTRICT',
                                name='fk_owner_template_selections_template_id_presentation_templates'),
        sa.PrimaryKeyConstraint('id', name='pk_owner_template_selections'),
    )
    op.create_index('ix_owner_template_selections_owner_key', 'owner_template_selections', ['owner_key'])
    op.create_index('ix_owner_template_selections_client_id', 'owner_template_selections', ['client_id'])
    op.create_index('ix_owner_template_selections_subclient_id', 'owner_template_selections', ['subclient_id'])

    op.create_table(
        'presentations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('owner_key', sa.String(80), nullable=False),
        sa.Column('client_id', sa.Uuid(), nullable=False),
        sa.Column('subclient_id', sa.Uuid(), nullable=True),
        sa.Column('competence_id', sa.Uuid(), nullable=False),
        sa.Column('template_id', sa.Uuid(), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('current_revision', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.String(120), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('current_revision >= 1', name='ck_presentations_current_revision_positive'),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='RESTRICT',
                                name='fk_presentations_client_id_clients'),
        sa.ForeignKeyConstraint(['subclient_id'], ['subclients.id'], ondelete='RESTRICT',
                                name='fk_presentations_subclient_id_subclients'),
        sa.ForeignKeyConstraint(['competence_id'], ['competences.id'], ondelete='RESTRICT',
                                name='fk_presentations_competence_id_competences'),
        sa.ForeignKeyConstraint(['template_id'], ['presentation_templates.id'], ondelete='RESTRICT',
                                name='fk_presentations_template_id_presentation_templates'),
        sa.PrimaryKeyConstraint('id', name='pk_presentations'),
    )
    op.create_index('ix_presentations_owner_key', 'presentations', ['owner_key'])
    op.create_index('ix_presentations_client_id', 'presentations', ['client_id'])
    op.create_index('ix_presentations_subclient_id', 'presentations', ['subclient_id'])
    op.create_index('ix_presentations_competence_id', 'presentations', ['competence_id'])

    op.create_table(
        'presentation_revisions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('presentation_id', sa.Uuid(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('document_json', sa.Text(), nullable=False),
        sa.Column('document_hash', sa.String(64), nullable=False),
        sa.Column('sources_json', sa.Text(), nullable=False),
        sa.Column('sources_hash', sa.String(64), nullable=False),
        sa.Column('primary_revision_id', sa.Uuid(), nullable=False),
        sa.Column('primary_approval_id', sa.Uuid(), nullable=False),
        sa.Column('change_summary', sa.Text(), nullable=False),
        sa.Column('previous_hash', sa.String(64), nullable=True),
        sa.Column('revision_hash', sa.String(64), nullable=False),
        sa.Column('created_by', sa.String(120), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('number >= 1', name='ck_presentation_revisions_number_positive'),
        sa.ForeignKeyConstraint(['presentation_id'], ['presentations.id'], ondelete='RESTRICT',
                                name='fk_presentation_revisions_presentation_id_presentations'),
        sa.ForeignKeyConstraint(['primary_revision_id'], ['competence_revisions.id'], ondelete='RESTRICT',
                                name='fk_presentation_revisions_primary_revision_id_competence_revisions'),
        sa.ForeignKeyConstraint(['primary_approval_id'], ['approvals.id'], ondelete='RESTRICT',
                                name='fk_presentation_revisions_primary_approval_id_approvals'),
        sa.PrimaryKeyConstraint('id', name='pk_presentation_revisions'),
        sa.UniqueConstraint('presentation_id', 'number', name='uq_presentation_revisions_presentation_id_number'),
    )
    op.create_index('ix_presentation_revisions_primary_revision_id', 'presentation_revisions',
                    ['primary_revision_id'])

    for ddl in _TRIGGERS.values():
        op.execute(ddl)


def downgrade() -> None:
    # Apresentações salvas não são apagadas por engano: exige confirmação explícita (procedimento administrativo).
    bind = op.get_bind()
    count = bind.execute(sa.text('SELECT COUNT(*) FROM presentations')).scalar()
    if count and os.getenv(DESTRUCTIVE_DOWNGRADE_VAR) != '1':
        raise RuntimeError(f'downgrade recusado: há {count} apresentação(ões) salvas; defina '
                           f'{DESTRUCTIVE_DOWNGRADE_VAR}=1 somente com backup e decisão explícita')
    for name in _TRIGGERS:
        op.execute(f'DROP TRIGGER IF EXISTS {name}')
    op.drop_index('ix_presentation_revisions_primary_revision_id', table_name='presentation_revisions')
    op.drop_table('presentation_revisions')
    for col in ('competence_id', 'subclient_id', 'client_id', 'owner_key'):
        op.drop_index(f'ix_presentations_{col}', table_name='presentations')
    op.drop_table('presentations')
    for col in ('subclient_id', 'client_id', 'owner_key'):
        op.drop_index(f'ix_owner_template_selections_{col}', table_name='owner_template_selections')
    op.drop_table('owner_template_selections')
    op.drop_table('presentation_templates')
