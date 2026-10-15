"""Regras de negócio do cadastro (F01): conexões, clientes e subclientes.

Exclusão segura (prioriza desativação lógica):
- Cliente/subcliente ativo não pode ser excluído (409): desative primeiro.
- Cliente com subclientes não pode ser excluído (409); FK RESTRICT reforça no banco.
- Conexão referenciada por cliente/subcliente não pode ser excluída (409).
Desativar um cliente NÃO altera o status gravado dos subclientes; `effective_active`
de cada subcliente passa a ser False enquanto o cliente estiver inativo.
"""
from __future__ import annotations

import logging
import uuid
from typing import Literal

from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas
from app.errors import bad_request, conflict, not_found
from app.orm import Client, Connection, Subclient, name_key

logger = logging.getLogger('afrika.registry')
StatusFilter = Literal['all', 'active', 'inactive']


def _commit(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        msg = str(exc.orig).upper()
        if 'UNIQUE' in msg:
            raise conflict('duplicate_name', 'Já existe um registro com este nome') from None
        if 'FOREIGN KEY' in msg:
            raise conflict('reference_conflict', 'A operação violaria a integridade referencial') from None
        raise


def _like(q: str) -> str:
    escaped = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f'%{escaped}%'


def _status_clause(column, status: StatusFilter):
    return {'active': column.is_(True), 'inactive': column.is_(False)}.get(status)


# ---------------------------------------------------------------- conexões

def _connection_or_404(session: Session, connection_id: uuid.UUID) -> Connection:
    conn = session.get(Connection, connection_id)
    if conn is None:
        raise not_found('connection')
    return conn


def _resolve_connection(session: Session, connection_id: uuid.UUID | None) -> None:
    if connection_id is not None and session.get(Connection, connection_id) is None:
        raise bad_request('connection_not_found', 'connection_id não corresponde a uma conexão cadastrada')


def _connection_usage(session: Session, connection_id: uuid.UUID) -> tuple[int, int]:
    clients = session.scalar(select(func.count()).select_from(Client).where(Client.connection_id == connection_id))
    subs = session.scalar(select(func.count()).select_from(Subclient).where(Subclient.connection_id == connection_id))
    return clients or 0, subs or 0


def connection_out(session: Session, conn: Connection) -> schemas.ConnectionOut:
    clients, subs = _connection_usage(session, conn.id)
    return schemas.ConnectionOut.model_validate(conn).model_copy(
        update={'client_count': clients, 'subclient_count': subs})


def _ensure_connection_name_free(session: Session, name: str, exclude: uuid.UUID | None = None) -> None:
    stmt = select(Connection.id).where(Connection.name_key == name_key(name))
    if exclude is not None:
        stmt = stmt.where(Connection.id != exclude)
    if session.scalar(stmt) is not None:
        raise conflict('duplicate_name', 'Já existe uma conexão com este nome')


def list_connections(session: Session, limit: int, offset: int) -> schemas.Page[schemas.ConnectionOut]:
    total = session.scalar(select(func.count()).select_from(Connection)) or 0
    rows = session.scalars(select(Connection).order_by(Connection.name_key, Connection.id).limit(limit).offset(offset))
    return schemas.Page(items=[connection_out(session, c) for c in rows], total=total, limit=limit, offset=offset)


def get_connection(session: Session, connection_id: uuid.UUID) -> schemas.ConnectionOut:
    return connection_out(session, _connection_or_404(session, connection_id))


def create_connection(session: Session, data: schemas.ConnectionCreate) -> schemas.ConnectionOut:
    _ensure_connection_name_free(session, data.name)
    conn = Connection(name=data.name, description=data.description, region=data.region.value,
                      credential_ref=data.credential_ref)
    session.add(conn)
    _commit(session)
    logger.info('conexão criada id=%s', conn.id)
    return connection_out(session, conn)


def update_connection(session: Session, connection_id: uuid.UUID,
                      data: schemas.ConnectionUpdate) -> schemas.ConnectionOut:
    conn = _connection_or_404(session, connection_id)
    changes = data.changes()
    if 'name' in changes:
        _ensure_connection_name_free(session, changes['name'], exclude=conn.id)
    if 'region' in changes:
        changes['region'] = changes['region'].value
    for key, value in changes.items():
        setattr(conn, key, value)
    _commit(session)
    logger.info('conexão atualizada id=%s campos=%s', conn.id, sorted(changes))
    return connection_out(session, conn)


def delete_connection(session: Session, connection_id: uuid.UUID) -> None:
    conn = _connection_or_404(session, connection_id)
    clients, subs = _connection_usage(session, conn.id)
    if clients or subs:
        raise conflict('connection_in_use',
                       f'Conexão em uso por {clients} cliente(s) e {subs} subcliente(s); remova as referências antes')
    session.delete(conn)
    _commit(session)
    logger.info('conexão excluída id=%s', connection_id)


# ---------------------------------------------------------------- clientes

def _client_or_404(session: Session, client_id: uuid.UUID) -> Client:
    client = session.get(Client, client_id)
    if client is None:
        if session.get(Subclient, client_id) is not None:
            raise bad_request('nested_subclient_not_allowed',
                              'O identificador pertence a um subcliente; subclientes não podem conter subclientes')
        raise not_found('client')
    return client


def _subclient_counts(session: Session, client_id: uuid.UUID) -> tuple[int, int]:
    total, active = session.execute(
        select(func.count(), func.coalesce(func.sum(case((Subclient.is_active, 1), else_=0)), 0))
        .where(Subclient.client_id == client_id)).one()
    return int(total), int(active)


def client_out(session: Session, client: Client) -> schemas.ClientOut:
    total, active = _subclient_counts(session, client.id)
    return schemas.ClientOut.model_validate(client).model_copy(
        update={'subclient_count': total, 'active_subclient_count': active})


def _ensure_client_name_free(session: Session, name: str, exclude: uuid.UUID | None = None) -> None:
    stmt = select(Client.id).where(Client.name_key == name_key(name))
    if exclude is not None:
        stmt = stmt.where(Client.id != exclude)
    if session.scalar(stmt) is not None:
        raise conflict('duplicate_name', 'Já existe um cliente com este nome')


def list_clients(session: Session, limit: int, offset: int, status: StatusFilter = 'all',
                 q: str | None = None) -> schemas.Page[schemas.ClientOut]:
    stmt = select(Client)
    clause = _status_clause(Client.is_active, status)
    if clause is not None:
        stmt = stmt.where(clause)
    if q:
        pattern = _like(q)
        stmt = stmt.where(or_(Client.name.ilike(pattern, escape='\\'), Client.display_name.ilike(pattern, escape='\\')))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(stmt.order_by(Client.name_key, Client.id).limit(limit).offset(offset)).unique()
    return schemas.Page(items=[client_out(session, c) for c in rows], total=total, limit=limit, offset=offset)


def get_client(session: Session, client_id: uuid.UUID) -> schemas.ClientOut:
    return client_out(session, _client_or_404(session, client_id))


def create_client(session: Session, data: schemas.ClientCreate) -> schemas.ClientOut:
    _ensure_client_name_free(session, data.name)
    _resolve_connection(session, data.connection_id)
    client = Client(name=data.name, display_name=data.display_name or data.name, description=data.description,
                    is_active=data.is_active, report_mode=data.report_mode.value, connection_id=data.connection_id,
                    timezone=data.timezone)
    session.add(client)
    _commit(session)
    session.refresh(client)
    logger.info('cliente criado id=%s', client.id)
    return client_out(session, client)


def update_client(session: Session, client_id: uuid.UUID, data: schemas.ClientUpdate) -> schemas.ClientOut:
    client = _client_or_404(session, client_id)
    changes = data.changes()
    if 'name' in changes:
        _ensure_client_name_free(session, changes['name'], exclude=client.id)
    if 'connection_id' in changes:
        _resolve_connection(session, changes['connection_id'])
    if 'report_mode' in changes:
        changes['report_mode'] = changes['report_mode'].value
    for key, value in changes.items():
        setattr(client, key, value)
    _commit(session)
    session.refresh(client)
    logger.info('cliente atualizado id=%s campos=%s', client.id, sorted(changes))
    return client_out(session, client)


def delete_client(session: Session, client_id: uuid.UUID) -> None:
    client = _client_or_404(session, client_id)
    if client.is_active:
        raise conflict('client_active', 'Desative o cliente antes de excluí-lo')
    total, _ = _subclient_counts(session, client.id)
    if total:
        raise conflict('client_has_subclients',
                       f'Cliente possui {total} subcliente(s); mantenha-o desativado ou exclua os subclientes antes')
    session.delete(client)
    _commit(session)
    logger.info('cliente excluído id=%s', client_id)


# ---------------------------------------------------------------- subclientes

def _subclient_or_404(session: Session, subclient_id: uuid.UUID) -> Subclient:
    sub = session.get(Subclient, subclient_id)
    if sub is None:
        raise not_found('subclient')
    return sub


def subclient_out(sub: Subclient) -> schemas.SubclientOut:
    if sub.connection is not None:
        effective, source = sub.connection, 'subclient'
    elif sub.client.connection is not None:
        effective, source = sub.client.connection, 'client'
    else:
        effective, source = None, 'none'
    return schemas.SubclientOut(
        id=sub.id, client_id=sub.client_id, name=sub.name, display_name=sub.display_name,
        is_active=sub.is_active, effective_active=sub.is_active and sub.client.is_active,
        connection_id=sub.connection_id,
        effective_connection=schemas.ConnectionSummary.model_validate(effective) if effective else None,
        connection_source=source, created_at=sub.created_at, updated_at=sub.updated_at)


def _ensure_subclient_name_free(session: Session, client_id: uuid.UUID, name: str,
                                exclude: uuid.UUID | None = None) -> None:
    stmt = select(Subclient.id).where(Subclient.client_id == client_id, Subclient.name_key == name_key(name))
    if exclude is not None:
        stmt = stmt.where(Subclient.id != exclude)
    if session.scalar(stmt) is not None:
        raise conflict('duplicate_name', 'Já existe um subcliente com este nome neste cliente')


def list_subclients(session: Session, client_id: uuid.UUID, limit: int, offset: int,
                    status: StatusFilter = 'all') -> schemas.Page[schemas.SubclientOut]:
    _client_or_404(session, client_id)
    stmt = select(Subclient).where(Subclient.client_id == client_id)
    clause = _status_clause(Subclient.is_active, status)
    if clause is not None:
        stmt = stmt.where(clause)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(stmt.order_by(Subclient.name_key, Subclient.id).limit(limit).offset(offset)).unique()
    return schemas.Page(items=[subclient_out(s) for s in rows], total=total, limit=limit, offset=offset)


def get_subclient(session: Session, subclient_id: uuid.UUID) -> schemas.SubclientOut:
    return subclient_out(_subclient_or_404(session, subclient_id))


def create_subclient(session: Session, client_id: uuid.UUID, data: schemas.SubclientCreate) -> schemas.SubclientOut:
    client = _client_or_404(session, client_id)
    _ensure_subclient_name_free(session, client.id, data.name)
    _resolve_connection(session, data.connection_id)
    sub = Subclient(client_id=client.id, name=data.name, display_name=data.display_name or data.name,
                    is_active=data.is_active, connection_id=data.connection_id)
    session.add(sub)
    _commit(session)
    session.refresh(sub)
    logger.info('subcliente criado id=%s cliente=%s', sub.id, client.id)
    return subclient_out(sub)


def update_subclient(session: Session, subclient_id: uuid.UUID, data: schemas.SubclientUpdate) -> schemas.SubclientOut:
    sub = _subclient_or_404(session, subclient_id)
    changes = data.changes()
    if 'name' in changes:
        _ensure_subclient_name_free(session, sub.client_id, changes['name'], exclude=sub.id)
    if 'connection_id' in changes:
        _resolve_connection(session, changes['connection_id'])
    for key, value in changes.items():
        setattr(sub, key, value)
    _commit(session)
    session.refresh(sub)
    logger.info('subcliente atualizado id=%s campos=%s', sub.id, sorted(changes))
    return subclient_out(sub)


def delete_subclient(session: Session, subclient_id: uuid.UUID) -> None:
    sub = _subclient_or_404(session, subclient_id)
    if sub.is_active:
        raise conflict('subclient_active', 'Desative o subcliente antes de excluí-lo')
    session.delete(sub)
    _commit(session)
    logger.info('subcliente excluído id=%s', subclient_id)

