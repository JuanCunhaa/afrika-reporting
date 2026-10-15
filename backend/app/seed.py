"""Dados SINTÉTICOS da demo F00. Só rodam por comando explícito (`python -m app.cli seed-demo`).

Idempotente: registros já existentes (mesmo nome) são mantidos como estão; nada é sobrescrito nem apagado.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.orm import Client, Connection, ReportMode, Subclient, VeracodeRegion, name_key
from app.presentations import templates

DEMO_CONNECTION = 'Conexão sintética (demo)'
DEMO_DESCRIPTION = 'Dados sintéticos (F00) — não representa cliente real'


def seed_demo(session: Session) -> dict[str, int]:
    created = {'connections': 0, 'clients': 0, 'subclients': 0}

    conn = session.scalar(select(Connection).where(Connection.name_key == name_key(DEMO_CONNECTION)))
    if conn is None:
        conn = Connection(name=DEMO_CONNECTION, description=DEMO_DESCRIPTION, region=VeracodeRegion.COMMERCIAL.value,
                          credential_ref='env:AFRIKA_DEMO_VERACODE')
        session.add(conn)
        session.flush()
        created['connections'] += 1

    def client(name: str, mode: ReportMode, connection: Connection | None) -> Client:
        existing = session.scalar(select(Client).where(Client.name_key == name_key(name)))
        if existing is not None:
            return existing
        row = Client(name=name, display_name=name, description=DEMO_DESCRIPTION, report_mode=mode.value,
                     connection_id=connection.id if connection else None)
        session.add(row)
        session.flush()
        created['clients'] += 1
        return row

    client('Cliente Demonstração', ReportMode.CONSOLIDATED, None)
    with_bus = client('Cliente com BUs (Sintético)', ReportMode.BOTH, conn)
    for name in ('TI', 'Marketing'):
        exists = session.scalar(select(Subclient.id).where(Subclient.client_id == with_bus.id, Subclient.name_key == name_key(name)))
        if exists is None:
            session.add(Subclient(client_id=with_bus.id, name=name, display_name=name))
            created['subclients'] += 1

    session.commit()
    # F06A: templates DEMONSTRATIVOS (sintéticos, tema provisório). Idempotente.
    created['templates'] = len(templates.install_builtin(session, 'seed-demo')['created'])
    return created
