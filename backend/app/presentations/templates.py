"""Templates versionados (F06A): armazenamento append-only, templates DEMONSTRATIVOS embutidos e escolha por dono.

- Versão de template é imutável (gatilho). Mudança = nova versão; apresentações existentes continuam apontando para
  a versão com que foram criadas.
- Templates embutidos são SINTÉTICOS e usam o tema neutro provisório: não são o template oficial da Afrika.
- Cada cliente/subcliente escolhe seu template (histórico append-only). Subcliente sem escolha herda a do cliente.
"""
from __future__ import annotations

import copy
import json
import uuid

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError, conflict
from app.orm import OwnerTemplateSelection, PresentationTemplate, TemplateOrigin, utcnow
from app.presentations import themes
from app.presentations.document import TemplateDefinition, validate_template
from app.scopes import store
from app.snapshots import audit
from app.snapshots.values import canonical, sha256

_THEME = {'id': 'neutral-demo', 'version': 1}
_SEV = ['sast.policy.open.by_severity', 'sca.policy.open.by_severity']


def _contracts(*metric_ids: str) -> dict[str, list[int]]:
    return {m: [1] for m in metric_ids}


# Definições embutidas: (chave, versão) -> definição. NUNCA alterar uma versão publicada: crie a próxima.
BUILTIN: dict[tuple[str, int], dict] = {
    ('demo-executivo', 1): {
        'name': 'Executivo mensal (demonstrativo)',
        'description': 'Estrutura sintética para diretoria: capa, sumário, KPIs, comparação, severidades, série, '
                       'ranking, recomendações e encerramento. Tema provisório.',
        'theme': _THEME,
        'metric_contracts': _contracts('apps.total', *_SEV, 'sast.policy.open.top_applications'),
        'slides': [
            {'slot_id': 'capa', 'type': 'cover', 'required': True,
             'fields': {'title': 'Relatório mensal de segurança de aplicações', 'subtitle': 'Visão executiva'},
             'options': {'show_presenters': True}},
            {'slot_id': 'sumario', 'type': 'executive_summary', 'required': True,
             'fields': {'title': 'Sumário executivo'}, 'metrics': ['apps.total', 'sast.policy.open.by_severity']},
            {'slot_id': 'kpis', 'type': 'kpis', 'required_metrics': True,
             'fields': {'title': 'Indicadores principais'}, 'metrics': ['apps.total', *_SEV]},
            {'slot_id': 'comparacao', 'type': 'month_comparison', 'fields': {'title': 'Mês atual × anterior'},
             'metrics': ['apps.total', *_SEV]},
            {'slot_id': 'severidade-sast', 'type': 'severity_distribution',
             'fields': {'title': 'SAST (Policy) por severidade', 'chart_title': 'Findings abertos por severidade'},
             'metrics': ['sast.policy.open.by_severity']},
            {'slot_id': 'serie-sast', 'type': 'line_chart',
             'fields': {'title': 'Evolução SAST (Policy)', 'chart_title': 'Findings abertos — total mensal'},
             'metrics': ['sast.policy.open.by_severity'], 'options': {'months': 6}},
            {'slot_id': 'top-apps', 'type': 'top10_ranking',
             'fields': {'title': 'Top 10 aplicações (SAST Policy)'},
             'metrics': ['sast.policy.open.top_applications'], 'options': {'top_n': 10}},
            {'slot_id': 'recomendacoes', 'type': 'recommendations', 'fields': {'title': 'Recomendações'}},
            {'slot_id': 'encerramento', 'type': 'closing', 'required': True, 'fields': {'title': 'Obrigado'},
             'options': {'show_presenters': True}},
        ],
    },
    ('demo-tecnico', 1): {
        'name': 'Técnico AppSec (demonstrativo)',
        'description': 'Estrutura sintética para times técnicos: distribuição por BU, séries de 12 meses, rankings '
                       'SAST/SCA e tabela de indicadores. Tema provisório.',
        'theme': _THEME,
        'metric_contracts': _contracts('apps.total', 'apps.by_business_unit', *_SEV, 'sast.policy.open.by_cwe',
                                       'sca.policy.open.top_components', 'apps.without_team', 'licenses.usage'),
        'slides': [
            {'slot_id': 'capa', 'type': 'cover', 'required': True,
             'fields': {'title': 'Relatório técnico AppSec'}, 'options': {'show_presenters': True}},
            {'slot_id': 'kpis', 'type': 'kpis', 'fields': {'title': 'Panorama'},
             'metrics': ['apps.total', *_SEV, 'apps.without_team']},
            {'slot_id': 'sev-sast', 'type': 'severity_distribution', 'fields': {'title': 'SAST Policy'},
             'metrics': ['sast.policy.open.by_severity']},
            {'slot_id': 'sev-sca', 'type': 'severity_distribution', 'fields': {'title': 'SCA Policy'},
             'metrics': ['sca.policy.open.by_severity']},
            {'slot_id': 'apps-bu', 'type': 'bar_chart', 'fields': {'title': 'Aplicações por Business Unit'},
             'metrics': ['apps.by_business_unit'], 'options': {'data_mode': 'breakdown'}},
            {'slot_id': 'serie-apps', 'type': 'bar_chart', 'fields': {'title': 'Aplicações — 12 meses'},
             'metrics': ['apps.total'], 'options': {'data_mode': 'history', 'months': 12}},
            {'slot_id': 'serie-findings', 'type': 'line_chart', 'fields': {'title': 'SAST × SCA — 12 meses'},
             'metrics': _SEV, 'options': {'months': 12}},
            {'slot_id': 'top-cwe', 'type': 'top10_ranking', 'fields': {'title': 'Top 10 CWE (SAST Policy)'},
             'metrics': ['sast.policy.open.by_cwe']},
            {'slot_id': 'top-componentes', 'type': 'top10_ranking',
             'fields': {'title': 'Top 10 componentes (SCA Policy)'}, 'metrics': ['sca.policy.open.top_components']},
            {'slot_id': 'tabela', 'type': 'metric_table', 'fields': {'title': 'Indicadores da competência'},
             'metrics': ['apps.total', *_SEV, 'apps.without_team', 'licenses.usage']},
            {'slot_id': 'observacoes', 'type': 'recommendations', 'fields': {'title': 'Observações'}},
            {'slot_id': 'encerramento', 'type': 'closing', 'required': True, 'fields': {'title': 'Encerramento'}},
        ],
    },
    ('demo-minimo', 1): {
        'name': 'Mínimo (demonstrativo)',
        'description': 'Capa, tabela de indicadores e encerramento — para donos com poucos indicadores aprovados.',
        'theme': _THEME,
        'metric_contracts': _contracts('apps.total'),
        'slides': [
            {'slot_id': 'capa', 'type': 'cover', 'required': True, 'fields': {'title': 'Relatório AppSec'}},
            {'slot_id': 'tabela', 'type': 'metric_table', 'fields': {'title': 'Indicadores'},
             'metrics': ['apps.total']},
            {'slot_id': 'encerramento', 'type': 'closing', 'required': True, 'fields': {'title': 'Obrigado'}},
        ],
    },
}


# F06B — template Afrika (16 slots na mesma sequência do PowerPoint de referência). Textos editoriais são
# PLACEHOLDERS genéricos e indicadores entram só por metric_id: serve a qualquer cliente/subcliente (slots não
# obrigatórios podem ser removidos; zonas e indicadores são editáveis).
_AF = {'id': 'afrika', 'version': 1}
_SAST, _SCA = 'sast.policy.open.by_severity', 'sca.policy.open.by_severity'
_MATRIX = ['Tema | Situação atual | Ação recomendada | Próximo passo',
           'Tema 1 | Descreva a situação observada | Descreva a ação recomendada | Defina o próximo passo',
           'Tema 2 | Descreva a situação observada | Descreva a ação recomendada | Defina o próximo passo',
           'Tema 3 | Descreva a situação observada | Descreva a ação recomendada | Defina o próximo passo']
BUILTIN[('afrika-modelo', 1)] = {
    'name': 'Afrika — relatório mensal (modelo)',
    'description': 'Sequência do template de referência Afrika: capa, divisores de seção, painéis compostos '
                   '(KPIs, gráficos, grupos, severidades, rankings), matrizes de ação e encerramento.',
    'theme': _AF,
    'metric_contracts': _contracts(
        'apps.total', 'apps.without_team', 'apps.unclassified', 'apps.multiple_teams', 'apps.loc.total',
        'apps.by_business_unit', _SAST, _SCA, 'sast.policy.new_in_period.by_severity', 'sast.sandbox.open.by_severity',
        'sast.open.distinct', 'sca.open.distinct', 'sast.policy.open.top_applications', 'sast.policy.open.by_cwe',
        'sca.policy.open.top_components', 'sca.policy.open.top_vulnerabilities'),
    'slides': [
        {'slot_id': 'capa', 'type': 'cover', 'required': True,
         'fields': {'title': 'Relatório mensal de AppSec', 'subtitle': 'Segurança de aplicações'},
         'options': {'show_presenters': True}},
        {'slot_id': 'secao-abertura', 'type': 'section', 'fields': {'title': 'Panorama', 'subtitle': '01'}},
        {'slot_id': 'secao-indicadores', 'type': 'section', 'fields': {'title': 'Indicadores', 'subtitle': '02'}},
        {'slot_id': 'secao-detalhes', 'type': 'section', 'fields': {'title': 'Detalhamento', 'subtitle': '03'}},
        {'slot_id': 'painel-kpis', 'type': 'dashboard', 'layout': 'painel-kpis', 'required_metrics': True,
         'fields': {'title': 'Visão geral do mês', 'body': 'Comentário editorial sobre os destaques do mês.'},
         'zones': {'band': {'metrics': ['apps.total', _SAST, _SCA]},
                   'cards': {'metrics': ['sast.policy.new_in_period.by_severity', 'apps.without_team',
                                         'apps.unclassified']},
                   'table': {'title': 'Inventário', 'metrics': ['apps.total', 'apps.without_team',
                                                                'apps.multiple_teams']},
                   'text': {}}},
        {'slot_id': 'painel-graficos', 'type': 'dashboard', 'layout': 'painel-graficos',
         'fields': {'title': 'Evolução e distribuição', 'items': ['Destaque editorial 1', 'Destaque editorial 2']},
         'zones': {'band': {'metrics': ['apps.total', 'sast.open.distinct']}, 'list': {},
                   'donut_a': {'title': 'SAST (Policy)', 'metrics': [_SAST]},
                   'donut_b': {'title': 'SCA (Policy)', 'metrics': [_SCA]},
                   'detail': {'title': 'Mês atual × anterior', 'metrics': ['apps.total', _SAST]},
                   'chart': {'title': 'Findings abertos — 6 meses', 'metrics': [_SAST, _SCA], 'chart': 'combo',
                             'months': 6}}},
        {'slot_id': 'painel-grupos', 'type': 'dashboard', 'layout': 'painel-grupos',
         'fields': {'title': 'SAST e SCA', 'items': ['Observação editorial 1', 'Observação editorial 2',
                                                     'Observação editorial 3']},
         'zones': {'group_a': {'title': 'SAST', 'metrics': [_SAST, 'sast.policy.new_in_period.by_severity',
                                                           'sast.sandbox.open.by_severity']},
                   'group_b': {'title': 'SCA', 'metrics': [_SCA, 'sca.open.distinct']},
                   'detail': {'metrics': ['apps.total', 'apps.loc.total']}, 'list': {},
                   'chart': {'title': 'Aplicações — 6 meses', 'metrics': ['apps.total'], 'chart': 'bar',
                             'data_mode': 'history', 'months': 6}}},
        {'slot_id': 'painel-severidades', 'type': 'dashboard', 'layout': 'painel-severidades',
         'fields': {'title': 'Severidades em produção', 'items': ['Observação editorial 1', 'Observação editorial 2']},
         'zones': {'group_a': {'title': 'SAST (Policy)', 'metrics': [_SAST]},
                   'group_b': {'title': 'SCA (Policy)', 'metrics': [_SCA]},
                   'detail': {'title': 'Mês atual × anterior', 'metrics': [_SAST, _SCA]}, 'list': {}}},
        {'slot_id': 'painel-severidades-dev', 'type': 'dashboard', 'layout': 'painel-severidades',
         'fields': {'title': 'Severidades em desenvolvimento', 'items': ['Observação editorial 1']},
         'zones': {'group_a': {'title': 'SAST (Sandbox)', 'metrics': ['sast.sandbox.open.by_severity']},
                   'group_b': {'title': 'SAST distintos', 'metrics': ['sast.open.distinct']},
                   'detail': {'title': 'Mês atual × anterior', 'metrics': ['sast.sandbox.open.by_severity']},
                   'list': {}}},
        {'slot_id': 'ranking-aplicacoes', 'type': 'dashboard', 'layout': 'painel-tabela-grafico',
         'fields': {'title': 'Aplicações com mais findings', 'subtitle': 'SAST (Policy)',
                    'items': ['Recomendação editorial 1', 'Recomendação editorial 2'],
                    'caption': 'Distribuição de aplicações por Business Unit (revisão aprovada).'},
         'zones': {'table': {'title': 'Top 5 aplicações', 'metrics': ['sast.policy.open.top_applications'],
                             'top_n': 5}, 'notes': {},
                   'chart': {'title': 'Aplicações por Business Unit', 'metrics': ['apps.by_business_unit'],
                             'chart': 'bar'}}},
        {'slot_id': 'ranking-componentes', 'type': 'dashboard', 'layout': 'painel-tabela-grafico',
         'fields': {'title': 'Componentes com mais findings', 'subtitle': 'SCA (Policy)',
                    'items': ['Recomendação editorial 1'],
                    'caption': 'Top CWE em SAST (Policy) na revisão aprovada.'},
         'zones': {'table': {'title': 'Top 5 componentes', 'metrics': ['sca.policy.open.top_components'],
                             'top_n': 5}, 'notes': {},
                   'chart': {'title': 'Top CWE (SAST Policy)', 'metrics': ['sast.policy.open.by_cwe'],
                             'chart': 'bar'}}},
        {'slot_id': 'destaque-vulnerabilidades', 'type': 'dashboard', 'layout': 'painel-destaque-tabela',
         'fields': {'title': 'Vulnerabilidades em destaque', 'subtitle': 'SCA (Policy)'},
         'zones': {'highlight': {'title': 'Findings SCA abertos em produção', 'metrics': [_SCA]},
                   'table': {'title': 'Vulnerabilidades com mais aplicações afetadas',
                             'metrics': ['sca.policy.open.top_vulnerabilities'], 'top_n': 10}}},
        {'slot_id': 'secao-plano', 'type': 'section', 'fields': {'title': 'Plano de ação', 'subtitle': '04'}},
        {'slot_id': 'matriz-acoes', 'type': 'recommendations', 'layout': 'matrix',
         'fields': {'title': 'Plano de ação', 'items': _MATRIX}},
        {'slot_id': 'matriz-acompanhamento', 'type': 'recommendations', 'layout': 'matrix',
         'fields': {'title': 'Acompanhamento', 'items': _MATRIX}},
        {'slot_id': 'encerramento', 'type': 'closing', 'required': True,
         'fields': {'title': 'Obrigado', 'subtitle': 'Próximos passos',
                    'items': ['Contato | Texto editável de contato', 'Próxima reunião | Data e pauta (editável)',
                              'Dúvidas | Canal de atendimento (editável)', 'Materiais | Onde encontrar os anexos']},
         'options': {'show_presenters': True}},
    ],
}


# F06C — `afrika-modelo@2`: os MESMOS 16 slots/layouts da v1 (copiados, não reescritos), apontando para o tema
# `afrika@2` (semântica de cores do PO). A v1 continua intacta (hash fixado em teste) e apresentações criadas com ela
# não mudam. Só `capa` e `encerramento` são obrigatórios: os demais slots podem ser escolhidos na criação
# (`slots`) conforme os indicadores disponíveis do dono — nenhuma apresentação precisa ter 16 slides.
BUILTIN[('afrika-modelo', 2)] = {
    **copy.deepcopy(BUILTIN[('afrika-modelo', 1)]),
    'description': 'Sequência do template de referência Afrika (16 slots opcionais, exceto capa e encerramento) com o '
                   'tema afrika@2: severidade por nível semântico e variação comprovada por direção do indicador.',
    'theme': {'id': 'afrika', 'version': 2},
}


def parse_definition(raw: dict, session: Session | None = None) -> TemplateDefinition:
    try:
        defn = TemplateDefinition.model_validate(raw)
    except ValidationError as exc:  # sem `input`: nada do que foi enviado volta na resposta
        raise ApiError(422, 'invalid_template', 'Template inválido',
                       [{'field': '.'.join(str(x) for x in e['loc']), 'message': e['msg'], 'type': e['type']}
                        for e in exc.errors()[:100]]) from None
    validate_template(defn, lambda key, version: themes.exists(session, key, version))
    return defn


def definition_of(t: PresentationTemplate) -> TemplateDefinition:
    return TemplateDefinition.model_validate(json.loads(t.definition_json))


def definition_hash(defn: TemplateDefinition) -> str:
    return sha256(defn.model_dump(mode='json'))


def template_out(t: PresentationTemplate, *, with_definition: bool = False) -> dict:
    out = {'id': str(t.id), 'key': t.template_key, 'version': t.version, 'name': t.name,
           'description': t.description, 'theme': {'id': t.theme_id, 'version': t.theme_version},
           'origin': t.origin, 'definition_hash': t.definition_hash, 'created_by': t.created_by,
           'created_at': t.created_at.isoformat()}
    if with_definition:
        out['definition'] = json.loads(t.definition_json)
    return out


# ---------------------------------------------------------------- consulta

def get(session: Session, key: str, version: int | None = None) -> PresentationTemplate:
    q = select(PresentationTemplate).where(PresentationTemplate.template_key == key)
    q = q.where(PresentationTemplate.version == version) if version is not None else \
        q.order_by(PresentationTemplate.version.desc()).limit(1)
    t = session.scalar(q)
    if t is None:
        raise ApiError(404, 'template_not_found', 'Template (ou versão) não encontrado')
    return t


def list_all(session: Session) -> list[dict]:
    rows = session.scalars(select(PresentationTemplate).order_by(PresentationTemplate.template_key,
                                                                 PresentationTemplate.version)).all()
    by_key: dict[str, list[PresentationTemplate]] = {}
    for t in rows:
        by_key.setdefault(t.template_key, []).append(t)
    return [{**template_out(vs[-1]), 'versions': [v.version for v in vs]} for vs in by_key.values()]


# ---------------------------------------------------------------- escrita (append-only)

def _insert(session: Session, key: str, version: int, defn: TemplateDefinition, origin: TemplateOrigin,
            operator: str) -> PresentationTemplate:
    t = PresentationTemplate(template_key=key, version=version, name=defn.name, description=defn.description,
                             theme_id=defn.theme.id, theme_version=defn.theme.version, origin=origin.value,
                             definition_json=canonical(defn.model_dump(mode='json')),
                             definition_hash=definition_hash(defn), created_by=operator)
    session.add(t)
    session.flush()
    audit.append(session, 'template.version_created', actor=operator,
                 details={'template': key, 'version': version, 'origin': origin.value,
                          'definition_hash': t.definition_hash})
    return t


def create(session: Session, key: str, raw: dict, operator: str) -> PresentationTemplate:
    defn = parse_definition(raw, session)
    if session.scalar(select(PresentationTemplate.id).where(PresentationTemplate.template_key == key).limit(1)):
        raise conflict('template_exists', 'Já existe template com esta chave: publique uma nova versão')
    t = _insert(session, key, 1, defn, TemplateOrigin.CUSTOM, operator)
    _commit_or_conflict(session)
    return t


def create_version(session: Session, key: str, raw: dict, operator: str,
                   expected_version: int) -> PresentationTemplate:
    current = get(session, key)
    if current.origin == TemplateOrigin.BUILTIN.value:
        raise conflict('builtin_template_readonly', 'Templates demonstrativos embutidos não recebem versões pela '
                                                    'API: crie um template próprio a partir dele')
    if current.version != expected_version:
        raise conflict('template_conflict', f'O template está na versão {current.version}, não {expected_version}')
    defn = parse_definition(raw, session)
    if definition_hash(defn) == current.definition_hash:
        raise conflict('template_unchanged', 'Definição idêntica à versão vigente')
    number = (session.scalar(select(func.max(PresentationTemplate.version))
                             .where(PresentationTemplate.template_key == key)) or 0) + 1
    t = _insert(session, key, number, defn, TemplateOrigin.CUSTOM, operator)
    _commit_or_conflict(session)
    return t


def _commit_or_conflict(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise conflict('template_conflict', 'Outra versão foi publicada ao mesmo tempo; recarregue') from None


def install_builtin(session: Session, operator: str) -> dict:
    """Idempotente: insere as versões embutidas ausentes; versão já existente com conteúdo diferente = erro."""
    created, kept = [], []
    for (key, version), raw in BUILTIN.items():
        defn = parse_definition(raw)
        existing = session.scalar(select(PresentationTemplate).where(PresentationTemplate.template_key == key,
                                                                     PresentationTemplate.version == version))
        if existing is not None:
            if existing.definition_hash != definition_hash(defn):
                raise conflict('builtin_template_mismatch', f'{key} v{version} já existe com outro conteúdo')
            kept.append(f'{key}@{version}')
            continue
        _insert(session, key, version, defn, TemplateOrigin.BUILTIN, operator)
        created.append(f'{key}@{version}')
    _commit_or_conflict(session)
    return {'created': created, 'existing': kept}


# ---------------------------------------------------------------- escolha por dono

def select_for_owner(session: Session, kind: str, owner_id: uuid.UUID, key: str, version: int,
                     operator: str) -> dict:
    owner = store.get_owner(session, kind, owner_id)
    t = get(session, key, version)
    session.add(OwnerTemplateSelection(owner_key=owner.key, client_id=owner.client.id,
                                       subclient_id=None if owner.subclient is None else owner.subclient.id,
                                       template_id=t.id, selected_by=operator, selected_at=utcnow()))
    audit.append(session, 'template.selected', owner_key=owner.key, actor=operator,
                 details={'template': key, 'version': version})
    _commit_or_conflict(session)
    return selection_of(session, owner)


def _latest_selection(session: Session, owner_key: str) -> OwnerTemplateSelection | None:
    return session.scalar(select(OwnerTemplateSelection).where(OwnerTemplateSelection.owner_key == owner_key)
                          .order_by(OwnerTemplateSelection.id.desc()).limit(1))


def selection_of(session: Session, owner: store.Owner) -> dict:
    sel, inherited = _latest_selection(session, owner.key), False
    if sel is None and owner.kind == 'subclient':
        sel, inherited = _latest_selection(session, f'client:{owner.client.id}'), True
    if sel is None:
        return {'owner_key': owner.key, 'template': None, 'inherited': False}
    t = session.get(PresentationTemplate, sel.template_id)
    return {'owner_key': owner.key, 'template': template_out(t), 'inherited': inherited,
            'selected_by': sel.selected_by, 'selected_at': sel.selected_at.isoformat()}


def resolve_for_owner(session: Session, owner: store.Owner) -> PresentationTemplate | None:
    sel = selection_of(session, owner)
    return None if sel['template'] is None else session.get(PresentationTemplate, uuid.UUID(sel['template']['id']))
