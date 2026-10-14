"""Persistência local (SQLite + SQLAlchemy) e integração com Alembic.

O esquema é criado/atualizado SOMENTE por migrations Alembic (`python -m app.cli migrate`).
Nada aqui chama `create_all()` nem apaga dados.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
DEFAULT_DB_PATH = REPO_ROOT / 'data' / 'afrika-reporting.sqlite3'
DATABASE_URL_ENV = 'AFRIKA_DATABASE_URL'


class SchemaNotReadyError(RuntimeError):
    """Banco ausente ou com migrations pendentes."""


def database_url() -> str:
    return os.getenv(DATABASE_URL_ENV) or f'sqlite:///{DEFAULT_DB_PATH.as_posix()}'


def _enable_sqlite_foreign_keys(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute('PRAGMA foreign_keys=ON')
    cur.close()


def make_engine(url: str, *, enforce_foreign_keys: bool = True) -> Engine:
    is_sqlite = make_url(url).get_backend_name() == 'sqlite'
    # hide_parameters: valores enviados ao banco nunca aparecem em logs nem em mensagens de exceção.
    engine = create_engine(
        url,
        hide_parameters=True,
        connect_args={'check_same_thread': False} if is_sqlite else {},
    )
    if is_sqlite and enforce_foreign_keys:
        event.listen(engine, 'connect', _enable_sqlite_foreign_keys)
    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def sqlite_file(url: str) -> Path | None:
    u = make_url(url)
    if u.get_backend_name() != 'sqlite' or not u.database or u.database == ':memory:':
        return None
    return Path(u.database)


# ---------------------------------------------------------------- Alembic

def alembic_config(url: str | None = None) -> Config:
    cfg = Config(str(BACKEND_DIR / 'alembic.ini'))
    cfg.set_main_option('script_location', str(BACKEND_DIR / 'migrations'))
    # Passado por atributo (não pelo .ini) para evitar interpolação e não depender de arquivo.
    cfg.attributes['database_url'] = url or database_url()
    return cfg


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def upgrade(url: str | None = None, revision: str = 'head') -> None:
    url = url or database_url()
    path = sqlite_file(url)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(url), revision)


def downgrade(url: str, revision: str) -> None:
    command.downgrade(alembic_config(url), revision)


def assert_schema_ready(engine: Engine) -> None:
    """Falha cedo se o banco não existe ou não está na última migration. Nunca cria nem altera nada."""
    path = sqlite_file(str(engine.url))
    if path is not None and not path.exists():
        raise SchemaNotReadyError(
            f'Banco não encontrado em {path}. Execute: python -m app.cli migrate')
    current, head = current_revision(engine), head_revision()
    if current != head:
        raise SchemaNotReadyError(
            f'Esquema do banco na revisão {current!r}, esperado {head!r}. Execute: python -m app.cli migrate')


def iter_session(factory: sessionmaker[Session]) -> Iterator[Session]:
    with factory() as session:
        yield session
