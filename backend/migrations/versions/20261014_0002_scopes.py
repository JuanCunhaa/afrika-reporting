"""F03: escopos versionados por domínio (applications, users, scans, sca) para clientes e subclientes.

Versões são append-only: gatilhos impedem alterar o conteúdo, reativar versão substituída e excluir versões.

Revision ID: 0002_scopes
Revises: 0001_registry
Create Date: 2026-10-14
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0002_scopes'
down_revision: str | None = '0001_registry'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DOMAINS = "domain IN ('applications', 'users', 'scans', 'sca')"

# Conteúdo de uma versão nunca muda: qualquer correção é uma versão nova.
_TRIGGERS = {
    'trg_scope_versions_immutable': """
        CREATE TRIGGER trg_scope_versions_immutable
        BEFORE UPDATE OF id, definition_id, version, rule_json, options_json, rule_hash, connection_mode,
                         coverage_ack, note, created_at ON scope_versions
        BEGIN SELECT RAISE(ABORT, 'scope_version_immutable'); END""",
    'trg_scope_versions_status': """
        CREATE TRIGGER trg_scope_versions_status
        BEFORE UPDATE OF status ON scope_versions
        WHEN NOT (OLD.status = 'active' AND NEW.status IN ('active', 'superseded'))
        BEGIN SELECT RAISE(ABORT, 'scope_version_status_transition'); END""",
    'trg_scope_versions_no_delete': """
        CREATE TRIGGER trg_scope_versions_no_delete
        BEFORE DELETE ON scope_versions
        BEGIN SELECT RAISE(ABORT, 'scope_version_delete_forbidden'); END""",
}


def upgrade() -> None:
    op.create_table(
        'scope_definitions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('client_id', sa.Uuid(), nullable=False),
        sa.Column('subclient_id', sa.Uuid(), nullable=True),
        sa.Column('owner_key', sa.String(80), nullable=False),
        sa.Column('domain', sa.String(20), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(_DOMAINS, name='ck_scope_definitions_domain'),
        sa.CheckConstraint("status IN ('active', 'disabled')", name='ck_scope_definitions_status'),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='RESTRICT',
                                name='fk_scope_definitions_client_id_clients'),
        sa.ForeignKeyConstraint(['subclient_id'], ['subclients.id'], ondelete='RESTRICT',
                                name='fk_scope_definitions_subclient_id_subclients'),
        sa.PrimaryKeyConstraint('id', name='pk_scope_definitions'),
        sa.UniqueConstraint('owner_key', 'domain', name='uq_scope_definitions_owner_key_domain'),
    )
    op.create_index('ix_scope_definitions_client_id', 'scope_definitions', ['client_id'])
    op.create_index('ix_scope_definitions_subclient_id', 'scope_definitions', ['subclient_id'])
    op.create_table(
        'scope_versions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('definition_id', sa.Uuid(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('rule_json', sa.Text(), nullable=False),
        sa.Column('options_json', sa.Text(), nullable=False),
        sa.Column('rule_hash', sa.String(64), nullable=False),
        sa.Column('connection_mode', sa.String(20), nullable=False),
        sa.Column('coverage_ack', sa.Boolean(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'superseded')", name='ck_scope_versions_status'),
        sa.CheckConstraint('version >= 1', name='ck_scope_versions_version_positive'),
        sa.CheckConstraint("connection_mode IN ('client', 'shared', 'separate', 'none')",
                           name='ck_scope_versions_connection_mode'),
        sa.ForeignKeyConstraint(['definition_id'], ['scope_definitions.id'], ondelete='RESTRICT',
                                name='fk_scope_versions_definition_id_scope_definitions'),
        sa.PrimaryKeyConstraint('id', name='pk_scope_versions'),
        sa.UniqueConstraint('definition_id', 'version', name='uq_scope_versions_definition_id_version'),
    )
    op.create_index('uq_scope_versions_one_active', 'scope_versions', ['definition_id'], unique=True,
                    sqlite_where=sa.text("status = 'active'"))
    for ddl in _TRIGGERS.values():
        op.execute(ddl)


def downgrade() -> None:
    # Remove o esquema F03 (inclusive o histórico de versões). Só por comando explícito.
    for name in _TRIGGERS:
        op.execute(f'DROP TRIGGER IF EXISTS {name}')
    op.drop_index('uq_scope_versions_one_active', table_name='scope_versions')
    op.drop_table('scope_versions')
    op.drop_index('ix_scope_definitions_subclient_id', table_name='scope_definitions')
    op.drop_index('ix_scope_definitions_client_id', table_name='scope_definitions')
    op.drop_table('scope_definitions')
