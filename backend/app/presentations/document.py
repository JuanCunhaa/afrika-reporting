"""Esquemas tipados do template e do documento de apresentação (F06A) e suas regras de validação.

- Nem template nem documento têm campo de VALOR: `extra='forbid'` recusa `value`, `number`, etc. Indicadores entram
  só por `metric_id`; números vêm sempre da revisão aprovada vinculada.
- Template: slots ordenados (tipo, layout, campos editoriais padrão, indicadores, opções), obrigatoriedade por slot
  (`required` = não removível; `required_metrics` = indicadores do slot precisam ter valor aprovado) e
  compatibilidade com versões de contrato (`metric_contracts`).
- Documento: cópia editável dos slots (incluir, remover, reordenar, editar textos e escolher indicadores
  compatíveis), sempre revalidada contra o template.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_serializer

from app.errors import ApiError
from app.metrics.registry import REGISTRY
from app.presentations.catalog import DASHBOARD_LAYOUTS, SLIDE_TYPES, SlideType, ZoneKind, compatible, zone_compatible
from app.presentations.themes import builtin_exists

SCHEMA_VERSION = 1
MAX_SLIDES = 40
_NO_CONTROL = r'^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$'  # permite \t e \n em textos longos

Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200, pattern=_NO_CONTROL)]
Medium = Annotated[str, StringConstraints(strip_whitespace=True, max_length=600, pattern=_NO_CONTROL)]
Long = Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000, pattern=_NO_CONTROL)]
Item = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400, pattern=_NO_CONTROL)]
MetricId = Annotated[str, StringConstraints(min_length=1, max_length=80, pattern=r'^[a-z0-9_.]+$')]
SlotId = Annotated[str, StringConstraints(min_length=1, max_length=40, pattern=r'^[a-z0-9][a-z0-9-]*$')]
TemplateKey = Annotated[str, StringConstraints(min_length=2, max_length=60, pattern=r'^[a-z0-9][a-z0-9-]*$')]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120, pattern=_NO_CONTROL)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class _Evolving(_Strict):
    """Campos acrescentados depois da v1 do esquema são OMITIDOS da serialização quando têm o valor padrão: templates
    e documentos antigos continuam com exatamente o mesmo JSON canônico (e o mesmo hash de integridade)."""
    _OMIT_IF_DEFAULT: ClassVar[tuple[str, ...]] = ()

    @model_serializer(mode='wrap')
    def _omit_new_defaults(self, handler):
        data = handler(self)
        fields = type(self).model_fields
        for name in self._OMIT_IF_DEFAULT:
            if name in data and getattr(self, name) == fields[name].get_default(call_default_factory=True):
                del data[name]
        return data


ZoneId = Annotated[str, StringConstraints(min_length=1, max_length=30, pattern=r'^[a-z][a-z0-9_]*$')]


class Zone(_Strict):
    """Vinculação de uma zona do painel composto (F06B): título editável e indicadores (só por metric_id)."""
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120, pattern=_NO_CONTROL)] | None = None
    metrics: list[MetricId] = Field(default_factory=list, max_length=6)
    chart: Literal['bar', 'line', 'combo'] | None = None
    data_mode: Literal['breakdown', 'history'] | None = None
    months: Literal[6, 12] | None = None
    top_n: int | None = Field(default=None, ge=1, le=10)


class SlideFields(_Strict):
    title: Short | None = None
    subtitle: Medium | None = None
    body: Long | None = None
    items: list[Item] = Field(default_factory=list, max_length=12)
    chart_title: Short | None = None
    legend_title: Short | None = None
    caption: Medium | None = None
    notes: Long | None = None


class SlideOptions(_Strict):
    months: Literal[6, 12] | None = None
    data_mode: Literal['breakdown', 'history'] | None = None
    show_legend: bool | None = None
    show_values: bool | None = None
    show_presenters: bool | None = None
    top_n: int | None = Field(default=None, ge=1, le=10)


class TemplateSlot(_Evolving):
    _OMIT_IF_DEFAULT: ClassVar[tuple[str, ...]] = ('zones',)
    slot_id: SlotId
    type: SlideType
    layout: Annotated[str, StringConstraints(max_length=40)] | None = None
    required: bool = False
    required_metrics: bool = False
    fields: SlideFields = Field(default_factory=SlideFields)
    metrics: list[MetricId] = Field(default_factory=list, max_length=12)
    options: SlideOptions = Field(default_factory=SlideOptions)
    zones: dict[ZoneId, Zone] = Field(default_factory=dict, max_length=8)


class ThemeRef(_Strict):
    id: Annotated[str, StringConstraints(max_length=60)]
    version: int = Field(ge=1)


class TemplateDefinition(_Strict):
    name: Name
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ''
    theme: ThemeRef
    metric_contracts: dict[MetricId, list[Annotated[int, Field(ge=1)]]] = Field(default_factory=dict)
    slides: list[TemplateSlot] = Field(min_length=1, max_length=MAX_SLIDES)


class Slide(_Evolving):
    _OMIT_IF_DEFAULT: ClassVar[tuple[str, ...]] = ('zones',)
    slide_id: SlotId
    template_slot: SlotId | None = None
    type: SlideType
    layout: Annotated[str, StringConstraints(max_length=40)]
    fields: SlideFields = Field(default_factory=SlideFields)
    metrics: list[MetricId] = Field(default_factory=list, max_length=12)
    options: SlideOptions = Field(default_factory=SlideOptions)
    zones: dict[ZoneId, Zone] = Field(default_factory=dict, max_length=8)


def all_metrics(s: TemplateSlot | Slide) -> list[str]:
    """Indicadores do slide: os do próprio slide + os das zonas do painel (sem repetição, em ordem)."""
    out = list(s.metrics)
    for z in s.zones.values():
        out += [m for m in z.metrics if m not in out]
    return out


class Presenter(_Strict):
    name: Name
    role: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120, pattern=_NO_CONTROL)] | None = None


class Document(_Strict):
    schema_version: Literal[1] = SCHEMA_VERSION
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200,
                                            pattern=_NO_CONTROL)]
    presenters: list[Presenter] = Field(default_factory=list, max_length=10)
    slides: list[Slide] = Field(min_length=1, max_length=MAX_SLIDES)


# ---------------------------------------------------------------- validação

def _err(field: str, message: str, code: str) -> dict:
    return {'field': field, 'message': message, 'type': code}


def _raise(code: str, message: str, errors: list[dict]) -> None:
    if errors:
        raise ApiError(422, code, message, errors[:100])


def _zone_errors(where: str, type_: SlideType, layout: str | None, zones: dict[str, Zone]) -> list[dict]:
    out = []
    if type_ is not SlideType.DASHBOARD:
        if zones:
            out.append(_err(f'{where}.zones', 'Zonas só existem no painel composto', 'zones_not_applicable'))
        return out
    specs = DASHBOARD_LAYOUTS.get(layout or next(iter(DASHBOARD_LAYOUTS)), {})
    for zid, z in zones.items():
        spec = specs.get(zid)
        w = f'{where}.zones.{zid}'
        if spec is None:
            out.append(_err(w, f'Zona inexistente no layout {layout}', 'unknown_zone'))
            continue
        if not spec.min_metrics <= len(z.metrics) <= spec.max_metrics:
            out.append(_err(f'{w}.metrics', f'{spec.name} aceita de {spec.min_metrics} a {spec.max_metrics} '
                                            'indicador(es)', 'metric_count'))
        if len(set(z.metrics)) != len(z.metrics):
            out.append(_err(f'{w}.metrics', 'Indicador repetido na zona', 'duplicate_metric'))
        if z.chart is not None and z.chart not in spec.charts:
            out.append(_err(f'{w}.chart', f'Gráfico não aplicável à zona ({", ".join(spec.charts) or "nenhum"})',
                            'option_not_applicable'))
        if (z.data_mode or z.months) and spec.kind is not ZoneKind.CHART:
            out.append(_err(w, 'Série mensal só em zona de gráfico', 'option_not_applicable'))
        if z.top_n and spec.kind is not ZoneKind.RANKING:
            out.append(_err(f'{w}.top_n', 'Itens de ranking só em zona de ranking', 'option_not_applicable'))
        for i, mid in enumerate(z.metrics):
            if mid not in REGISTRY:
                out.append(_err(f'{w}.metrics[{i}]', 'Indicador inexistente no catálogo', 'unknown_metric'))
            elif not zone_compatible(spec, mid, z.chart or (spec.charts[0] if spec.charts else None), z.data_mode):
                out.append(_err(f'{w}.metrics[{i}]', f'{mid} não é compatível com a zona {spec.name}',
                                'incompatible_metric'))
    return out


def _slide_errors(where: str, type_: SlideType, layout: str | None, fields: SlideFields, metrics: list[str],
                  options: SlideOptions, *, check_required_fields: bool,
                  zones: dict[str, Zone] | None = None) -> list[dict]:
    spec = SLIDE_TYPES[type_]
    out = _zone_errors(where, type_, layout, zones or {})
    if layout is not None and layout not in spec.layouts:
        out.append(_err(f'{where}.layout', f'Layout inválido para {spec.name}: {", ".join(spec.layouts)}',
                        'invalid_layout'))
    for name, value in fields.model_dump().items():
        if name not in spec.editable_fields and value not in (None, '', []):
            out.append(_err(f'{where}.fields.{name}', f'Campo não editável em {spec.name}', 'field_not_editable'))
    if check_required_fields:
        for name in spec.required_fields:
            if not getattr(fields, name):
                out.append(_err(f'{where}.fields.{name}', 'Campo obrigatório', 'required_field'))
    for name, value in options.model_dump().items():
        if value is not None and name not in spec.options:
            out.append(_err(f'{where}.options.{name}', f'Opção não aplicável a {spec.name}', 'option_not_applicable'))
    if not spec.min_metrics <= len(metrics) <= spec.max_metrics:
        out.append(_err(f'{where}.metrics', f'{spec.name} aceita de {spec.min_metrics} a {spec.max_metrics} '
                                            'indicador(es)', 'metric_count'))
    if len(set(metrics)) != len(metrics):
        out.append(_err(f'{where}.metrics', 'Indicador repetido no slide', 'duplicate_metric'))
    for i, mid in enumerate(metrics):
        if mid not in REGISTRY:
            out.append(_err(f'{where}.metrics[{i}]', 'Indicador inexistente no catálogo', 'unknown_metric'))
        elif not compatible(spec, mid, options.data_mode):
            out.append(_err(f'{where}.metrics[{i}]', f'{mid} não é compatível com {spec.name}'
                                                     + (f' ({options.data_mode})' if options.data_mode else ''),
                            'incompatible_metric'))
    return out


def validate_template(defn: TemplateDefinition,
                      theme_exists: Callable[[str, int], bool] = builtin_exists) -> None:
    errors = []
    if not theme_exists(defn.theme.id, defn.theme.version):
        errors.append(_err('theme', 'Tema inexistente', 'unknown_theme'))
    ids = [s.slot_id for s in defn.slides]
    if len(set(ids)) != len(ids):
        errors.append(_err('slides', 'slot_id repetido', 'duplicate_slot'))
    used = set()
    for i, s in enumerate(defn.slides):
        errors += _slide_errors(f'slides[{i}]', s.type, s.layout, s.fields, s.metrics, s.options,
                                check_required_fields=False, zones=s.zones)
        if s.required_metrics and not all_metrics(s):
            errors.append(_err(f'slides[{i}].required_metrics', 'Slot sem indicadores não pode exigir indicadores',
                               'required_metrics_empty'))
        used |= set(all_metrics(s))
    for mid in sorted(used - set(defn.metric_contracts)):
        errors.append(_err(f'metric_contracts.{mid}', 'Declare as versões de contrato aceitas para cada indicador '
                                                      'usado', 'contract_versions_missing'))
    for mid, versions in defn.metric_contracts.items():
        if mid not in REGISTRY:
            errors.append(_err(f'metric_contracts.{mid}', 'Indicador inexistente no catálogo', 'unknown_metric'))
        elif not versions:
            errors.append(_err(f'metric_contracts.{mid}', 'Lista de versões vazia', 'contract_versions_missing'))
    _raise('invalid_template', 'Template inválido', errors)


def validate_document(doc: Document, defn: TemplateDefinition) -> None:
    """Documento editado continua coerente com o template: slots obrigatórios presentes (mesmo tipo), indicadores
    obrigatórios mantidos, tipos/layouts/campos/opções/indicadores válidos."""
    errors = []
    slots = {s.slot_id: s for s in defn.slides}
    ids = [s.slide_id for s in doc.slides]
    if len(set(ids)) != len(ids):
        errors.append(_err('slides', 'slide_id repetido', 'duplicate_slide'))
    seen_slots: dict[str, int] = {}
    for i, s in enumerate(doc.slides):
        where = f'slides[{i}]'
        errors += _slide_errors(where, s.type, s.layout, s.fields, s.metrics, s.options, check_required_fields=True,
                                zones=s.zones)
        if s.template_slot is None:
            continue
        slot = slots.get(s.template_slot)
        if slot is None:
            errors.append(_err(f'{where}.template_slot', 'Slot inexistente no template', 'unknown_slot'))
            continue
        if s.template_slot in seen_slots:
            errors.append(_err(f'{where}.template_slot', 'Slot do template usado mais de uma vez', 'duplicate_slot'))
        seen_slots[s.template_slot] = i
        if s.type != slot.type:
            errors.append(_err(f'{where}.type', 'O tipo de um slide do template não pode mudar', 'slot_type_changed'))
        if slot.required_metrics and not set(all_metrics(slot)) <= set(all_metrics(s)):
            errors.append(_err(f'{where}.metrics', 'Indicadores obrigatórios do template não podem ser removidos',
                               'required_metric_removed'))
    for slot in defn.slides:
        if slot.required and slot.slot_id not in seen_slots:
            errors.append(_err('slides', f'Slide obrigatório do template ausente: {slot.slot_id}',
                               'required_slide_removed'))
    _raise('invalid_document', 'Documento da apresentação inválido', errors)


def contract_versions(defn: TemplateDefinition, metric_id: str) -> list[int]:
    """Versões aceitas: as declaradas pelo template; indicador incluído pelo editor = versão vigente do catálogo."""
    if metric_id in defn.metric_contracts:
        return list(defn.metric_contracts[metric_id])
    c = REGISTRY.get(metric_id)
    return [] if c is None else [c.version]


def select_slots(doc: Document, defn: TemplateDefinition, slots: list[str]) -> tuple[Document, list[str]]:
    """F06C — seleção flexível: mantém só os slots escolhidos (na ordem do template). Slots obrigatórios do template
    (ex.: capa e encerramento) entram SEMPRE; slot inexistente => 422. Devolve (documento, obrigatórios incluídos)."""
    known = [s.slot_id for s in defn.slides]
    unknown = sorted({s for s in slots if s not in known})
    if unknown:
        raise ApiError(422, 'invalid_document', 'Slot inexistente no template',
                       [{'field': 'slots', 'message': s, 'type': 'unknown_slot'} for s in unknown])
    required = [s.slot_id for s in defn.slides if s.required]
    chosen = set(slots) | set(required)
    kept = [s for s in doc.slides if s.template_slot in chosen]
    return doc.model_copy(update={'slides': kept}), [s for s in required if s not in slots]


def initial_document(defn: TemplateDefinition, title: str) -> Document:
    slides = [Slide(slide_id=s.slot_id, template_slot=s.slot_id, type=s.type,
                    layout=s.layout or SLIDE_TYPES[s.type].layouts[0], fields=s.fields.model_copy(deep=True),
                    metrics=list(s.metrics), options=s.options.model_copy(deep=True),
                    zones={k: z.model_copy(deep=True) for k, z in s.zones.items()}) for s in defn.slides]
    for s in slides:  # campos obrigatórios vazios no template recebem o nome do tipo (editável)
        for name in SLIDE_TYPES[s.type].required_fields:
            if not getattr(s.fields, name):
                setattr(s.fields, name, SLIDE_TYPES[s.type].name)
    return Document(title=title, slides=slides)
