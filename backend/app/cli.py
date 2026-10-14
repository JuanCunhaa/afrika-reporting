"""Comandos locais. Execute a partir de `backend/`:

    python -m app.cli migrate      # cria/atualiza o esquema via Alembic (não apaga dados)
    python -m app.cli db-status    # mostra caminho do banco e revisão atual x esperada
    python -m app.cli seed-demo    # insere dados SINTÉTICOS da demo (idempotente)

Banco: AFRIKA_DATABASE_URL ou data/afrika-reporting.sqlite3 na raiz do repo.
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy.engine import make_url

from app import db
from app.seed import seed_demo


def _display_url(url: str) -> str:
    path = db.sqlite_file(url)
    return str(path) if path is not None else make_url(url).render_as_string(hide_password=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='python -m app.cli', description='Afrika Reporting — comandos locais')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('migrate', help='aplica migrations pendentes (alembic upgrade head)')
    sub.add_parser('db-status', help='revisão atual do banco x revisão esperada')
    sub.add_parser('seed-demo', help='insere dados sintéticos da demo F00 (idempotente)')
    args = parser.parse_args(argv)

    url = db.database_url()
    print(f'Banco: {_display_url(url)}')
    if args.command == 'migrate':
        db.upgrade(url)
        print(f'Esquema na revisão {db.head_revision()}')
        return 0

    path = db.sqlite_file(url)
    if path is not None and not path.exists():
        print('Banco inexistente. Execute: python -m app.cli migrate', file=sys.stderr)
        return 1
    engine = db.make_engine(url)
    try:
        if args.command == 'db-status':
            current, head = db.current_revision(engine), db.head_revision()
            print(f'Revisão atual: {current}  esperada: {head}  -> {"OK" if current == head else "MIGRATE NECESSÁRIO"}')
            return 0 if current == head else 1
        db.assert_schema_ready(engine)
        with db.session_factory(engine)() as session:
            created = seed_demo(session)
        print(f'Seed sintético: criados {created}')
        return 0
    except db.SchemaNotReadyError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
