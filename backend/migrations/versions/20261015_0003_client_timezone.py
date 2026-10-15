"""F04.1: fuso horário IANA por cliente (padrão America/Sao_Paulo) para as competências dos indicadores.

Revision ID: 0003_client_timezone
Revises: 0002_scopes
Create Date: 2026-10-15
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0003_client_timezone'
down_revision: str | None = '0002_scopes'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('clients') as batch:
        batch.add_column(sa.Column('timezone', sa.String(64), nullable=False, server_default='America/Sao_Paulo'))


def downgrade() -> None:
    with op.batch_alter_table('clients') as batch:
        batch.drop_column('timezone')
