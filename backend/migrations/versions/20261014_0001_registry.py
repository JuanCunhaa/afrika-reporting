"""F01: cadastro de conexões, clientes e subclientes.

Revision ID: 0001_registry
Revises:
Create Date: 2026-10-14
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0001_registry'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False)]


def upgrade() -> None:
    op.create_table(
        'connections',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('name_key', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('region', sa.String(20), nullable=False),
        sa.Column('credential_ref', sa.String(80), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("region IN ('commercial', 'european', 'federal')", name='ck_connections_region'),
        sa.PrimaryKeyConstraint('id', name='pk_connections'),
        sa.UniqueConstraint('name_key', name='uq_connections_name_key'),
    )
    op.create_table(
        'clients',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('name_key', sa.String(255), nullable=False),
        sa.Column('display_name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('report_mode', sa.String(20), nullable=False),
        sa.Column('connection_id', sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("report_mode IN ('consolidated', 'per_subclient', 'both')", name='ck_clients_report_mode'),
        sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ondelete='RESTRICT',
                                name='fk_clients_connection_id_connections'),
        sa.PrimaryKeyConstraint('id', name='pk_clients'),
        sa.UniqueConstraint('name_key', name='uq_clients_name_key'),
    )
    op.create_index('ix_clients_connection_id', 'clients', ['connection_id'])
    op.create_table(
        'subclients',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('client_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('name_key', sa.String(255), nullable=False),
        sa.Column('display_name', sa.String(200), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('connection_id', sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='RESTRICT',
                                name='fk_subclients_client_id_clients'),
        sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ondelete='RESTRICT',
                                name='fk_subclients_connection_id_connections'),
        sa.PrimaryKeyConstraint('id', name='pk_subclients'),
        sa.UniqueConstraint('client_id', 'name_key', name='uq_subclients_client_id_name_key'),
    )
    op.create_index('ix_subclients_connection_id', 'subclients', ['connection_id'])


def downgrade() -> None:
    # Remove o esquema F01 inteiro. Só é executado por comando explícito (nunca na inicialização).
    op.drop_index('ix_subclients_connection_id', table_name='subclients')
    op.drop_table('subclients')
    op.drop_index('ix_clients_connection_id', table_name='clients')
    op.drop_table('clients')
    op.drop_table('connections')
