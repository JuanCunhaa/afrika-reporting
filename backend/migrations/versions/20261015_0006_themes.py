"""F06B.1: temas visuais versionados (tokens completos) para apresentações.

Garantias no próprio banco (gatilhos), além das regras da aplicação:
- versões de tema são imutáveis e nunca excluídas (mudança = nova versão);
- temas embutidos (demonstrativos) ficam no código e não ocupam esta tabela.
Ativos (logos, fontes) NÃO ficam no banco: só a referência por hash SHA-256; os arquivos ficam num diretório local fora
do Git (AFRIKA_ASSET_DIR). Nenhuma tabela anterior é alterada.

Revision ID: 0006_themes
Revises: 0005_presentations
Create Date: 2026-10-15
"""
from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0006_themes'
down_revision: str | None = '0005_presentations'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DESTRUCTIVE_DOWNGRADE_VAR = 'AFRIKA_ALLOW_DESTRUCTIVE_DOWNGRADE'

_TRIGGERS = {
    'trg_presentation_themes_no_update': """
        CREATE TRIGGER trg_presentation_themes_no_update BEFORE UPDATE ON presentation_themes
        BEGIN SELECT RAISE(ABORT, 'presentation_themes_append_only'); END""",
    'trg_presentation_themes_no_delete': """
        CREATE TRIGGER trg_presentation_themes_no_delete BEFORE DELETE ON presentation_themes
        BEGIN SELECT RAISE(ABORT, 'presentation_themes_append_only'); END""",
}


def upgrade() -> None:
    op.create_table(
        'presentation_themes',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('theme_key', sa.String(60), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('provisional', sa.Boolean(), nullable=False),
        sa.Column('definition_json', sa.Text(), nullable=False),
        sa.Column('definition_hash', sa.String(64), nullable=False),
        sa.Column('created_by', sa.String(120), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('version >= 1', name='ck_presentation_themes_version_positive'),
        sa.PrimaryKeyConstraint('id', name='pk_presentation_themes'),
        sa.UniqueConstraint('theme_key', 'version', name='uq_presentation_themes_theme_key_version'),
    )
    for ddl in _TRIGGERS.values():
        op.execute(ddl)


def downgrade() -> None:
    # Temas próprios não são apagados por engano: exige confirmação explícita (procedimento administrativo).
    bind = op.get_bind()
    count = bind.execute(sa.text('SELECT COUNT(*) FROM presentation_themes')).scalar()
    if count and os.getenv(DESTRUCTIVE_DOWNGRADE_VAR) != '1':
        raise RuntimeError(f'Downgrade recusado: {count} versão(ões) de tema próprio seriam apagadas. '
                           f'Defina {DESTRUCTIVE_DOWNGRADE_VAR}=1 para confirmar.')
    for name in _TRIGGERS:
        op.execute(f'DROP TRIGGER IF EXISTS {name}')
    op.drop_table('presentation_themes')
