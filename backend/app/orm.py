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
    # F04.1: fuso IANA das competências do cliente (subclientes herdam).
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default='America/Sao_Paulo',
                                          server_default='America/Sao_Paulo')

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


# ---------------------------------------------------------------- F05: snapshots, revisões, aprovações e auditoria

class RevisionStatus(str, enum.Enum):
    DRAFT = 'DRAFT'
    READY_FOR_REVIEW = 'READY_FOR_REVIEW'
    APPROVED = 'APPROVED'


class SnapshotOrigin(str, enum.Enum):
    VERACODE = 'VERACODE'
    MANUAL = 'MANUAL'


class ValueType(str, enum.Enum):
    COUNT = 'count'
    DECIMAL = 'decimal'
    PERCENTAGE = 'percentage'
    BY_SEVERITY = 'by_severity'
    BREAKDOWN = 'breakdown'
    RANKING = 'ranking'


TECHNICAL_STATUSES = ('VALIDATED', 'INCOMPLETE', 'UNAVAILABLE', 'UNSUPPORTED', 'FAILED')
_TECH_IN = ', '.join(f"'{s}'" for s in TECHNICAL_STATUSES)


class CollectionRunRecord(Base):
    """Execução de coleta (F04) importada para um rascunho. Só metadados e resumos — nenhum finding, nenhuma
    credencial (a conexão aparece por id/nome/região). Imutável após a inserção (gatilhos)."""
    __tablename__ = 'collection_runs'
    __table_args__ = (CheckConstraint("kind IN ('METRICS')", name='kind'),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True)  # = run_id da execução F04
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default='METRICS')
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey('clients.id', ondelete='RESTRICT'), nullable=False, index=True)
    subclient_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey('subclients.id', ondelete='RESTRICT'), nullable=True, index=True)
    owner_key: Mapped[str] = mapped_column(String(80), nullable=False)
    competence_label: Mapped[str] = mapped_column(String(7), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    scope_refs_json: Mapped[str] = mapped_column(Text(), nullable=False)
    connection_json: Mapped[str] = mapped_column(Text(), nullable=False)
    population_json: Mapped[str] = mapped_column(Text(), nullable=False)
    collection_json: Mapped[str] = mapped_column(Text(), nullable=False)
    summary_json: Mapped[str] = mapped_column(Text(), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)


class Competence(TimestampMixin, Base):
    """Competência mensal (YYYY-MM) de um dono (cliente OU subcliente), no fuso vigente na criação."""
    __tablename__ = 'competences'
    __table_args__ = (CheckConstraint("label GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]'", name='label'),
                      UniqueConstraint('owner_key', 'label', name='uq_competences_owner_key_label'))

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey('clients.id', ondelete='RESTRICT'), nullable=False, index=True)
    subclient_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey('subclients.id', ondelete='RESTRICT'), nullable=True, index=True)
    owner_key: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(7), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)

    revisions: Mapped[list[CompetenceRevision]] = relationship(
        back_populates='competence', order_by='CompetenceRevision.number', passive_deletes='all')


class CompetenceRevision(TimestampMixin, Base):
    """Revisão de uma competência. DRAFT -> READY_FOR_REVIEW -> APPROVED (terminal, imutável por gatilho).
    `lock_version` = concorrência otimista: toda alteração exige a versão esperada; divergência => conflito."""
    __tablename__ = 'competence_revisions'
    __table_args__ = (CheckConstraint(f'status IN ({_in(RevisionStatus)})', name='status'),
                      CheckConstraint('number >= 1', name='number_positive'),
                      CheckConstraint('lock_version >= 1', name='lock_version_positive'),
                      UniqueConstraint('competence_id', 'number', name='uq_competence_revisions_competence_id_number'),
                      Index('uq_competence_revisions_one_open', 'competence_id', unique=True,
                            sqlite_where=text("status IN ('DRAFT', 'READY_FOR_REVIEW')")))

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    competence_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey('competences.id', ondelete='RESTRICT'), nullable=False)
    number: Mapped[int] = mapped_column(Integer(), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=RevisionStatus.DRAFT.value)
    base_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey('competence_revisions.id', ondelete='RESTRICT'), nullable=True)
    lock_version: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    required_metrics_json: Mapped[str] = mapped_column(Text(), nullable=False, default='[]')
    required_set_version: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    submitted_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    competence: Mapped[Competence] = relationship(back_populates='revisions')
    snapshots: Mapped[list[MetricSnapshot]] = relationship(
        back_populates='revision', order_by='MetricSnapshot.metric_id', passive_deletes='all')


class MetricSnapshot(TimestampMixin, Base):
    """Valor de UM indicador numa revisão. `value_json` = valor efetivo (NULL = ausente; '0' = zero legítimo).
    O valor observado na Veracode fica SEMPRE em `source_*`, mesmo quando o efetivo é manual."""
    __tablename__ = 'metric_snapshots'
    __table_args__ = (
        CheckConstraint(f'origin IN ({_in(SnapshotOrigin)})', name='origin'),
        CheckConstraint(f'value_type IN ({_in(ValueType)})', name='value_type'),
        CheckConstraint(f'source_status IS NULL OR source_status IN ({_TECH_IN})', name='source_status'),
        CheckConstraint("origin <> 'MANUAL' OR (value_json IS NOT NULL AND manual_justification IS NOT NULL "
                        "AND manual_operator IS NOT NULL AND manual_at IS NOT NULL)", name='manual_complete'),
        CheckConstraint("origin <> 'VERACODE' OR value_json IS NULL OR source_status = 'VALIDATED'",
                        name='veracode_value_validated'),
        CheckConstraint("source_value_json IS NULL OR source_status = 'VALIDATED'", name='source_value_validated'),
        UniqueConstraint('revision_id', 'metric_id', name='uq_metric_snapshots_revision_id_metric_id'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey('competence_revisions.id', ondelete='RESTRICT'), nullable=False)
    metric_id: Mapped[str] = mapped_column(String(80), nullable=False)
    contract_version: Mapped[int] = mapped_column(Integer(), nullable=False)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False)
    shape: Mapped[str] = mapped_column(String(20), nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    origin: Mapped[str] = mapped_column(String(10), nullable=False)
    value_json: Mapped[str | None] = mapped_column(Text(), nullable=True)
    source_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_value_json: Mapped[str | None] = mapped_column(Text(), nullable=True)
    source_partial_json: Mapped[str | None] = mapped_column(Text(), nullable=True)
    source_reasons_json: Mapped[str] = mapped_column(Text(), nullable=False, default='[]')
    dashboard_homologation: Mapped[str] = mapped_column(String(32), nullable=False)
    source_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    context: Mapped[str | None] = mapped_column(String(24), nullable=True)
    collected_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    temporal_json: Mapped[str] = mapped_column(Text(), nullable=False, default='{}')
    scope_refs_json: Mapped[str] = mapped_column(Text(), nullable=False, default='[]')
    provenance_json: Mapped[str] = mapped_column(Text(), nullable=False, default='{}')
    collection_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey('collection_runs.id', ondelete='RESTRICT'), nullable=True, index=True)
    manual_justification: Mapped[str | None] = mapped_column(Text(), nullable=True)
    manual_operator: Mapped[str | None] = mapped_column(String(120), nullable=True)
    manual_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    revision: Mapped[CompetenceRevision] = relationship(back_populates='snapshots')


class ManualChange(Base):
    """Registro APPEND-ONLY de cada alteração manual (valor anterior e novo, justificativa, operador declarado)."""
    __tablename__ = 'manual_changes'
    __table_args__ = (CheckConstraint(f'previous_origin IS NULL OR previous_origin IN ({_in(SnapshotOrigin)})',
                                      name='previous_origin'),
                      CheckConstraint(f'new_origin IN ({_in(SnapshotOrigin)})', name='new_origin'))

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey('metric_snapshots.id', ondelete='RESTRICT'), nullable=False, index=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey('competence_revisions.id', ondelete='RESTRICT'), nullable=False, index=True)
    metric_id: Mapped[str] = mapped_column(String(80), nullable=False)
    previous_value_json: Mapped[str | None] = mapped_column(Text(), nullable=True)
    new_value_json: Mapped[str | None] = mapped_column(Text(), nullable=True)
    previous_origin: Mapped[str | None] = mapped_column(String(10), nullable=True)
    new_origin: Mapped[str] = mapped_column(String(10), nullable=False)
    justification: Mapped[str] = mapped_column(Text(), nullable=False)
    operator: Mapped[str] = mapped_column(String(120), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)


class Approval(Base):
    """Aprovação APPEND-ONLY de uma revisão. Aprovador DECLARADO (sem autenticação): não é identidade comprovada.
    `content_hash` cobre o conteúdo da revisão; `chain_hash` encadeia as aprovações da competência."""
    __tablename__ = 'approvals'
    __table_args__ = (CheckConstraint("identity_mode IN ('DECLARED_UNAUTHENTICATED')", name='identity_mode'),
                      CheckConstraint('sequence >= 1', name='sequence_positive'),
                      UniqueConstraint('revision_id', name='uq_approvals_revision_id'),
                      UniqueConstraint('competence_id', 'sequence', name='uq_approvals_competence_id_sequence'))

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    competence_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey('competences.id', ondelete='RESTRICT'), nullable=False)
    revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey('competence_revisions.id', ondelete='RESTRICT'), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer(), nullable=False)
    approver: Mapped[str] = mapped_column(String(120), nullable=False)
    identity_mode: Mapped[str] = mapped_column(String(40), nullable=False, default='DECLARED_UNAUTHENTICATED')
    note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    approved_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_chain_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chain_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class AuditEvent(Base):
    """Evento de auditoria APPEND-ONLY, encadeado por hash (`prev_hash` único => cadeia linear, sem bifurcação)."""
    __tablename__ = 'audit_events'
    __table_args__ = (UniqueConstraint('prev_hash', name='uq_audit_events_prev_hash'),)

    id: Mapped[int] = mapped_column(Integer(), primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    owner_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    competence_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey('competences.id', ondelete='RESTRICT'), nullable=True, index=True)
    revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey('competence_revisions.id', ondelete='RESTRICT'), nullable=True)
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    details_json: Mapped[str] = mapped_column(Text(), nullable=False, default='{}')
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)


# ---------------------------------------------------------------- F06A: templates e apresentações

class TemplateOrigin(str, enum.Enum):
    BUILTIN = 'BUILTIN'  # template demonstrativo definido no código (dados sintéticos; tema provisório)
    CUSTOM = 'CUSTOM'    # criado pelo operador


class PresentationTemplate(Base):
    """Versão IMUTÁVEL de um template de apresentação (append-only por gatilho). Sem números: só estrutura,
    textos editoriais padrão, indicadores por `metric_id` e versões de contrato aceitas."""
    __tablename__ = 'presentation_templates'
    __table_args__ = (CheckConstraint(f'origin IN ({_in(TemplateOrigin)})', name='origin'),
                      CheckConstraint('version >= 1', name='version_positive'),
                      UniqueConstraint('template_key', 'version',
                                       name='uq_presentation_templates_template_key_version'))

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    template_key: Mapped[str] = mapped_column(String(60), nullable=False)
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text(), nullable=False, default='')
    theme_id: Mapped[str] = mapped_column(String(60), nullable=False)
    theme_version: Mapped[int] = mapped_column(Integer(), nullable=False)
    origin: Mapped[str] = mapped_column(String(10), nullable=False)
    definition_json: Mapped[str] = mapped_column(Text(), nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)


class OwnerTemplateSelection(Base):
    """Escolha de template por cliente/subcliente (append-only: a vigente é a mais recente)."""
    __tablename__ = 'owner_template_selections'

    id: Mapped[int] = mapped_column(Integer(), primary_key=True, autoincrement=True)
    owner_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey('clients.id', ondelete='RESTRICT'), nullable=False, index=True)
    subclient_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey('subclients.id', ondelete='RESTRICT'), nullable=True, index=True)
    template_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey('presentation_templates.id', ondelete='RESTRICT'), nullable=False)
    selected_by: Mapped[str] = mapped_column(String(120), nullable=False)
    selected_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)


class Presentation(TimestampMixin, Base):
    """Apresentação de UMA competência de um dono, a partir de um template. Identidade imutável (gatilho);
    o conteúdo vive em `presentation_revisions` (append-only). `current_revision` = concorrência otimista."""
    __tablename__ = 'presentations'
    __table_args__ = (CheckConstraint('current_revision >= 1', name='current_revision_positive'),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    owner_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey('clients.id', ondelete='RESTRICT'), nullable=False, index=True)
    subclient_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey('subclients.id', ondelete='RESTRICT'), nullable=True, index=True)
    competence_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey('competences.id', ondelete='RESTRICT'), nullable=False, index=True)
    template_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey('presentation_templates.id', ondelete='RESTRICT'), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    current_revision: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)

    revisions: Mapped[list[PresentationRevision]] = relationship(
        back_populates='presentation', order_by='PresentationRevision.number', passive_deletes='all')


class PresentationRevision(Base):
    """Revisão APPEND-ONLY do conteúdo editorial + fontes fixadas (revisões APROVADAS da F05, com hashes).
    Encadeada por hash (`previous_hash` -> `revision_hash`). Nunca guarda valores de indicadores."""
    __tablename__ = 'presentation_revisions'
    __table_args__ = (CheckConstraint('number >= 1', name='number_positive'),
                      UniqueConstraint('presentation_id', 'number',
                                       name='uq_presentation_revisions_presentation_id_number'))

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    presentation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey('presentations.id', ondelete='RESTRICT'), nullable=False)
    number: Mapped[int] = mapped_column(Integer(), nullable=False)
    document_json: Mapped[str] = mapped_column(Text(), nullable=False)
    document_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sources_json: Mapped[str] = mapped_column(Text(), nullable=False)
    sources_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    primary_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey('competence_revisions.id', ondelete='RESTRICT'), nullable=False, index=True)
    primary_approval_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey('approvals.id', ondelete='RESTRICT'), nullable=False)
    change_summary: Mapped[str] = mapped_column(Text(), nullable=False, default='')
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    presentation: Mapped[Presentation] = relationship(back_populates='revisions')
