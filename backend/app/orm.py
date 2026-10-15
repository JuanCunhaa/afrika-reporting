"""Modelos SQLAlchemy do cadastro (F01): conexões, clientes e subclientes.

Hierarquia fixa em dois níveis: Client -> Subclient. Subclient não possui
referência a outro subclient, logo não há como aninhar.
Conexões guardam somente metadados e uma REFERÊNCIA ao segredo (`credential_ref`),
nunca o segredo em si.
"""
from __future__ import annotations

import enum
import unicodedata
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, MetaData, String, Text,
    TypeDecorator, UniqueConstraint, Uuid, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates

NAMING_CONVENTION = {
    'ix': 'ix_%(column_0_label)s',
    'uq': 'uq_%(table_name)s_%(column_0_name)s',
    'ck': 'ck_%(table_name)s_%(constraint_name)s',
    'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s',
    'pk': 'pk_%(table_name)s',
}


class ReportMode(str, enum.Enum):
    CONSOLIDATED = 'consolidated'
    PER_SUBCLIENT = 'per_subclient'
    BOTH = 'both'


class ScopeDomain(str, enum.Enum):
    APPLICATIONS = 'applications'
    USERS = 'users'
    SCANS = 'scans'
    SCA = 'sca'


class ScopeStatus(str, enum.Enum):
    ACTIVE = 'active'
    DISABLED = 'disabled'


class ScopeVersionStatus(str, enum.Enum):
    ACTIVE = 'active'
    SUPERSEDED = 'superseded'


class VeracodeRegion(str, enum.Enum):
    COMMERCIAL = 'commercial'
    EUROPEAN = 'european'
    FEDERAL = 'federal'


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Grava em UTC sem tzinfo (SQLite) e devolve datetime com tzinfo=UTC."""
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError('datetime sem timezone não é aceito')
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=timezone.utc)


def name_key(name: str) -> str:
    """Chave de unicidade: NFKC + casefold (ignora caixa inclusive em acentos: 'Único' == 'único')."""
    return unicodedata.normalize('NFKC', name).casefold()


def _in(values: type[enum.Enum]) -> str:
    return ', '.join(f"'{v.value}'" for v in values)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class NamedMixin:
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_key: Mapped[str] = mapped_column(String(255), nullable=False)

    @validates('name')
    def _sync_name_key(self, _key, value: str) -> str:
        self.name_key = name_key(value)
        return value


def _same_as_created(context) -> datetime:
    return context.get_current_parameters()['created_at']


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_same_as_created,
                                                 onupdate=utcnow)


class Connection(NamedMixin, TimestampMixin, Base):
    __tablename__ = 'connections'
    __table_args__ = (CheckConstraint(f'region IN ({_in(VeracodeRegion)})', name='region'),
                      UniqueConstraint('name_key', name='uq_connections_name_key'))

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    region: Mapped[str] = mapped_column(String(20), nullable=False)
    credential_ref: Mapped[str] = mapped_column(String(80), nullable=False)


class Client(NamedMixin, TimestampMixin, Base):
    __tablename__ = 'clients'
    __table_args__ = (CheckConstraint(f'report_mode IN ({_in(ReportMode)})', name='report_mode'),
                      UniqueConstraint('name_key', name='uq_clients_name_key'))

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    report_mode: Mapped[str] = mapped_column(String(20), nullable=False, default=ReportMode.CONSOLIDATED.value)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey('connections.id', ondelete='RESTRICT'), nullable=True, index=True)

    connection: Mapped[Connection | None] = relationship(lazy='joined')
    subclients: Mapped[list[Subclient]] = relationship(back_populates='client', passive_deletes='all')


class Subclient(NamedMixin, TimestampMixin, Base):
    __tablename__ = 'subclients'
    __table_args__ = (UniqueConstraint('client_id', 'name_key', name='uq_subclients_client_id_name_key'),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey('clients.id', ondelete='RESTRICT'), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey('connections.id', ondelete='RESTRICT'), nullable=True, index=True)

    client: Mapped[Client] = relationship(back_populates='subclients', lazy='joined')
    connection: Mapped[Connection | None] = relationship(lazy='joined')


class ScopeDefinition(TimestampMixin, Base):
    """Escopo (F03) de um domínio para um cliente OU subcliente. Critérios vivem nas versões (imutáveis).

    `owner_key` = 'client:<uuid>' | 'subclient:<uuid>' garante 1 definição por dono+domínio (NULL não é único
    no SQLite). `client_id` é sempre o cliente principal (do subcliente, quando for o caso).
    """
    __tablename__ = 'scope_definitions'
    __table_args__ = (CheckConstraint(f'domain IN ({_in(ScopeDomain)})', name='domain'),
                      CheckConstraint(f'status IN ({_in(ScopeStatus)})', name='status'),
                      UniqueConstraint('owner_key', 'domain', name='uq_scope_definitions_owner_key_domain'))

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey('clients.id', ondelete='RESTRICT'), nullable=False, index=True)
    subclient_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey('subclients.id', ondelete='RESTRICT'), nullable=True, index=True)
    owner_key: Mapped[str] = mapped_column(String(80), nullable=False)
    domain: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ScopeStatus.ACTIVE.value)

    versions: Mapped[list[ScopeVersion]] = relationship(back_populates='definition', order_by='ScopeVersion.version',
                                                        passive_deletes='all')


class ScopeVersion(Base):
    """Versão IMUTÁVEL dos critérios (append-only; gatilhos no banco impedem UPDATE do conteúdo e DELETE).

    Só `status` muda, e apenas active -> superseded. Restaurar uma versão antiga cria uma versão nova.
    Guarda só a regra (IDs/valores de filtro) — nunca cópias de recursos Veracode.
    """
    __tablename__ = 'scope_versions'
    __table_args__ = (CheckConstraint(f'status IN ({_in(ScopeVersionStatus)})', name='status'),
                      CheckConstraint('version >= 1', name='version_positive'),
                      CheckConstraint("connection_mode IN ('client', 'shared', 'separate', 'none')",
                                      name='connection_mode'),
                      UniqueConstraint('definition_id', 'version', name='uq_scope_versions_definition_id_version'),
                      Index('uq_scope_versions_one_active', 'definition_id', unique=True,
                            sqlite_where=text("status = 'active'")))

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey('scope_definitions.id', ondelete='RESTRICT'), nullable=False)
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    rule_json: Mapped[str] = mapped_column(Text(), nullable=False)
    options_json: Mapped[str] = mapped_column(Text(), nullable=False)
    rule_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    connection_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    coverage_ack: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    definition: Mapped[ScopeDefinition] = relationship(back_populates='versions')
