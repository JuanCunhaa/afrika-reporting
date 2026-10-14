from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from app.db import database_url, make_engine
from app.orm import Base

config = context.config
if config.config_file_name is not None and not config.attributes.get('skip_logging_config'):
    # disable_existing_loggers=False: não silenciar loggers da aplicação/testes.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    return config.attributes.get('database_url') or database_url()


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True, dialect_opts={'paramstyle': 'named'})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # FKs desligadas durante migrations: o modo batch do SQLite recria tabelas.
    engine = make_engine(_url(), enforce_foreign_keys=False)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
