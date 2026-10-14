"""Schemas Pydantic da API de cadastro (F01).

Todos os modelos de entrada usam `extra='forbid'`: campos desconhecidos (ex.: `api_key`,
`parent_subclient_id`) geram 422 em vez de serem ignorados silenciosamente.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated, ClassVar, Generic, Literal, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.orm import ReportMode, VeracodeRegion

_CONTROL_CHARS = re.compile(r'[\x00-\x1f\x7f]')


def _no_control_chars(v: str) -> str:
    if _CONTROL_CHARS.search(v):
        raise ValueError('não pode conter caracteres de controle')
    return v


def _blank_to_none(v: str) -> str | None:
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', v):
        raise ValueError('não pode conter caracteres de controle')
    return v or None


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
                 AfterValidator(_no_control_chars)]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
                        AfterValidator(_no_control_chars)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000),
                        AfterValidator(_blank_to_none)] | None

# Referência ao segredo, nunca o segredo. Formato: env:NOME_DE_VARIAVEL.
# A resolução (leitura de NOME_API_ID / NOME_API_KEY no ambiente do backend) é escopo da F02.
CREDENTIAL_REF_PATTERN = r'^env:[A-Z][A-Z0-9_]{1,62}$'
_HEX_RUN = re.compile(r'[0-9A-F]{24,}')


def _credential_ref(v: str) -> str:
    if not re.fullmatch(CREDENTIAL_REF_PATTERN, v):
        raise ValueError('use o formato env:NOME_DA_VARIAVEL (A-Z, 0-9, _), sem o valor do segredo')
    if _HEX_RUN.search(v.replace('_', '')):
        raise ValueError('parece conter um segredo; informe apenas o nome da variável de ambiente')
    return v


CredentialRef = Annotated[str, StringConstraints(strip_whitespace=True, max_length=66),
                          AfterValidator(_credential_ref)]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra='forbid')


class PatchInput(StrictInput):
    """PATCH: só os campos enviados são alterados; `null` só é aceito nos campos anuláveis."""
    nullable_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode='after')
    def _reject_null_on_required(self):
        for field in self.model_fields_set - self.nullable_fields:
            if getattr(self, field) is None:
                raise ValueError(f'o campo {field!r} não aceita null')
        return self

    def changes(self) -> dict:
        return self.model_dump(exclude_unset=True)


class ApiOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)


T = TypeVar('T')


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------- conexões

class ConnectionCreate(StrictInput):
    name: Name
    description: Description = None
    region: VeracodeRegion
    credential_ref: CredentialRef


class ConnectionUpdate(PatchInput):
    nullable_fields: ClassVar[frozenset[str]] = frozenset({'description'})
    name: Name | None = None
    description: Description = None
    region: VeracodeRegion | None = None
    credential_ref: CredentialRef | None = None


class ConnectionSummary(ApiOutput):
    id: uuid.UUID
    name: str
    region: VeracodeRegion
    credential_ref: str


class ConnectionOut(ConnectionSummary):
    description: str | None
    client_count: int = 0
    subclient_count: int = 0
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- clientes

class ClientCreate(StrictInput):
    name: Name
    display_name: DisplayName | None = Field(default=None, description='Padrão: igual a name')
    description: Description = None
    is_active: bool = True
    report_mode: ReportMode = ReportMode.CONSOLIDATED
    connection_id: uuid.UUID | None = None


class ClientUpdate(PatchInput):
    nullable_fields: ClassVar[frozenset[str]] = frozenset({'description', 'connection_id'})
    name: Name | None = None
    display_name: DisplayName | None = None
    description: Description = None
    is_active: bool | None = None
    report_mode: ReportMode | None = None
    connection_id: uuid.UUID | None = None


class ClientOut(ApiOutput):
    id: uuid.UUID
    name: str
    display_name: str
    description: str | None
    is_active: bool
    report_mode: ReportMode
    connection_id: uuid.UUID | None
    connection: ConnectionSummary | None
    subclient_count: int = 0
    active_subclient_count: int = 0
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- subclientes

class SubclientCreate(StrictInput):
    name: Name
    display_name: DisplayName | None = Field(default=None, description='Padrão: igual a name')
    is_active: bool = True
    connection_id: uuid.UUID | None = Field(default=None, description='null = herda a conexão do cliente')


class SubclientUpdate(PatchInput):
    nullable_fields: ClassVar[frozenset[str]] = frozenset({'connection_id'})
    name: Name | None = None
    display_name: DisplayName | None = None
    is_active: bool | None = None
    connection_id: uuid.UUID | None = None


ConnectionSource = Literal['subclient', 'client', 'none']


class SubclientOut(ApiOutput):
    id: uuid.UUID
    client_id: uuid.UUID
    name: str
    display_name: str
    is_active: bool
    effective_active: bool = Field(description='is_active do subcliente E do cliente')
    connection_id: uuid.UUID | None = Field(description='Sobrescrita própria; null = herda do cliente')
    effective_connection: ConnectionSummary | None
    connection_source: ConnectionSource
    created_at: datetime
    updated_at: datetime
