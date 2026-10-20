"""Guia de conferência (F10): para cada indicador do catálogo, se pode ser comparado com a plataforma Veracode, onde
encontrar o número equivalente, os filtros que precisam coincidir e como o valor calculado vira linhas comparáveis.

Categorias (separadas, nunca somadas):
- APPLICABLE: existe número equivalente na plataforma; fica NOT_VERIFIED até a conferência humana registrar MATCH.
- NOT_APPLICABLE: conceito próprio do Afrika, identidade de deduplicação não comprovada, estado histórico ou sem
  fonte — não há "valor oficial" com a mesma definição.
- BLOCKED_EXTERNAL: a fonte que produziria o valor está bloqueada fora do projeto (Reporting API: HTTP 403).

Os caminhos na plataforma são INDICATIVOS (o agente não acessa o portal): o operador confirma filtros e data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.metrics.contracts import SEVERITY_LABELS
from app.metrics.registry import REGISTRY


class Category(StrEnum):
    APPLICABLE = 'APPLICABLE'
    NOT_APPLICABLE = 'NOT_APPLICABLE'
    BLOCKED_EXTERNAL = 'BLOCKED_EXTERNAL'


SEVERITY_LINES = [(k, k.replace('_', ' ').title()) for k in SEVERITY_LABELS.values()] + [('total', 'Total')]

_OPEN = ('Status Open; excluir mitigações APROVADAS (mitigação proposta/rejeitada continua aberta); todas as '
         'severidades (Very High … Informational)')
_POLICY = 'Contexto Policy (último scan de política = produção); sem sandboxes'
_SANDBOX = 'Cada sandbox separadamente (desenvolvimento), somando ocorrências; sem a Policy'
_SAME_SCOPE = 'Somente as aplicações do escopo do dono (lista na tela de prévia de escopos)'


@dataclass(frozen=True)
class Guide:
    category: Category
    reason: str = ''
    path: str = ''
    filters: tuple[str, ...] = ()
    # Como o valor vira linhas: ('scalar',) | ('severity',) | ('items', lista, campo_id, campo_rótulo, campo_valor) |
    # ('fields', ((campo, rótulo), ...))
    lines: tuple = ('scalar',)
    totals: tuple[tuple[str, str], ...] = field(default_factory=tuple)  # campos agregados extras em BREAKDOWN/RANKING


def _items(list_key: str, id_field: str, label_field: str, value_field: str) -> tuple:
    return ('items', list_key, id_field, label_field, value_field)


_NA_IDENTITY = ('Deduplicação entre contextos com identidade NÃO comprovada (contrato): o valor nunca fica VALIDATED; '
                'a plataforma não expõe o mesmo "distinto"')
_NA_HISTORY = ('Estado no fechamento da competência não é reconstruível pela API (só estado atual): vale o snapshot '
               'APROVADO ou a entrada manual justificada — comparar com o portal hoje confundiria atual × histórico')
_BLOCKED_REPORTING = ('Fonte = Reporting API (relatório FINDINGS/SCANS), HTTP 403 na conta de testes desde a F05; '
                      'POST não repetido sem mudança de permissão comprovada')

GUIDES: dict[str, Guide] = {
    'apps.total': Guide(Category.APPLICABLE, path='Portfólio → Applications (lista), contar aplicações do escopo',
                        filters=(_SAME_SCOPE,)),
    'apps.by_business_unit': Guide(
        Category.APPLICABLE, path='Applications → filtro Business Unit (uma BU por vez), contar no escopo',
        filters=(_SAME_SCOPE,), lines=_items('items', 'business_unit_id', 'name', 'applications'),
        totals=(('unknown', 'Sem BU'),)),
    'apps.by_team': Guide(
        Category.APPLICABLE, path='Applications → filtro Team (um Team por vez), contar no escopo',
        filters=(_SAME_SCOPE, 'Aplicação com vários Teams conta em cada Team'),
        lines=_items('items', 'team_id', 'name', 'applications'), totals=(('without_team', 'Sem Team'),)),
    'apps.without_team': Guide(Category.APPLICABLE, path='Applications → aplicações sem Team atribuído',
                               filters=(_SAME_SCOPE,)),
    'apps.multiple_teams': Guide(Category.APPLICABLE, path='Applications → aplicações com 2 ou mais Teams',
                                 filters=(_SAME_SCOPE,)),
    'apps.unclassified': Guide(Category.NOT_APPLICABLE, reason='Conceito do Afrika (universo do cliente menos '
                               'subclientes); não existe no portal'),
    'apps.by_policy_compliance': Guide(
        Category.APPLICABLE, path='Applications → coluna/filtro Policy Compliance (Pass, Did Not Pass, '
                                  'Conditional Pass, Not Assessed…)', filters=(_SAME_SCOPE, _POLICY),
        lines=_items('items', 'status', 'status', 'applications'), totals=(('unknown', 'Indeterminadas'),)),
    'apps.loc.total': Guide(Category.APPLICABLE, path='Perfil da aplicação → último scan estático da Policy → '
                            'Summary/Overview (Lines of Code); somar as aplicações do escopo',
                            filters=(_SAME_SCOPE, _POLICY)),
    'apps.total.at_period_end': Guide(Category.NOT_APPLICABLE, reason=_NA_HISTORY),

    'sast.policy.open.by_severity': Guide(
        Category.APPLICABLE, path='Perfil da aplicação → Policy scan → Findings/Triage Flaws (Static), agrupar por '
                                  'severidade; somar as aplicações', filters=(_SAME_SCOPE, _POLICY, _OPEN),
        lines=('severity',)),
    'sast.sandbox.open.by_severity': Guide(
        Category.APPLICABLE, path='Perfil da aplicação → Sandboxes → cada sandbox → Findings (Static), por severidade',
        filters=(_SAME_SCOPE, _SANDBOX, _OPEN), lines=('severity',)),
    'sast.sandbox.open.distinct': Guide(Category.NOT_APPLICABLE, reason=_NA_IDENTITY),
    'sast.open.distinct': Guide(Category.NOT_APPLICABLE, reason=_NA_IDENTITY),
    'sast.policy.open.by_cwe': Guide(
        Category.APPLICABLE, path='Findings (Static, Policy) agrupados por CWE; somar as aplicações',
        filters=(_SAME_SCOPE, _POLICY, _OPEN, 'Agrupar por CWE (não pela categoria do dashboard)'),
        lines=_items('top', 'cwe_id', 'name', 'findings'), totals=(('others', 'Outros CWEs'), ('total', 'Total'))),
    'sast.policy.open.top_applications': Guide(
        Category.APPLICABLE, path='Findings abertos (Static, Policy) por aplicação', filters=(_SAME_SCOPE, _POLICY,
                                                                                              _OPEN),
        lines=_items('top', 'application_guid', 'name', 'findings'), totals=(('total', 'Total'),)),
    'sast.policy.new_in_period.by_severity': Guide(
        Category.APPLICABLE, path='Findings (Static, Policy) com First Found Date dentro da competência, por '
                                  'severidade (qualquer status)',
        filters=(_SAME_SCOPE, _POLICY, 'First Found Date ∈ competência no fuso do cliente', 'Qualquer status'),
        lines=('severity',)),
    'sast.policy.open.by_first_found_month': Guide(
        Category.APPLICABLE, path='Findings abertos (Static, Policy) agrupados pelo mês de First Found Date',
        filters=(_SAME_SCOPE, _POLICY, _OPEN, 'Mês no fuso do cliente'),
        lines=_items('items', 'month', 'month', 'findings'), totals=(('total', 'Total'),)),
    'sast.policy.summary.by_severity': Guide(
        Category.APPLICABLE, path='Perfil da aplicação → último scan estático da Policy → Summary Report, flaws por '
                                  'severidade', filters=(_SAME_SCOPE, _POLICY, 'Build mais recente'),
        lines=('severity',)),
    'sast.policy.reconciliation': Guide(Category.NOT_APPLICABLE, reason='Indicador de qualidade de dados (Findings × '
                                        'Summary Report); não existe no portal'),
    'sast.policy.open.at_period_end': Guide(Category.NOT_APPLICABLE, reason=_NA_HISTORY),
    'sast.policy.resolved_in_period': Guide(Category.BLOCKED_EXTERNAL, reason=_BLOCKED_REPORTING),

    'sca.policy.open.by_severity': Guide(
        Category.APPLICABLE, path='Perfil da aplicação → Software Composition Analysis (Policy) → vulnerabilidades '
                                  'abertas por severidade; somar as aplicações',
        filters=(_SAME_SCOPE, _POLICY, _OPEN, 'Upload e agente vinculado juntos'), lines=('severity',)),
    'sca.sandbox.open.by_severity': Guide(
        Category.APPLICABLE, path='Perfil da aplicação → Sandboxes → cada sandbox → SCA, por severidade',
        filters=(_SAME_SCOPE, _SANDBOX, _OPEN), lines=('severity',)),
    'sca.open.distinct': Guide(Category.NOT_APPLICABLE, reason=_NA_IDENTITY),
    'sca.policy.open.top_components': Guide(
        Category.APPLICABLE, path='SCA (Policy) → bibliotecas vulneráveis, findings abertos por biblioteca+versão',
        filters=(_SAME_SCOPE, _POLICY, _OPEN), lines=_items('top', 'component_id', 'filename', 'findings'),
        totals=(('total', 'Total'),)),
    'sca.policy.open.top_vulnerabilities': Guide(
        Category.APPLICABLE, path='SCA (Policy) → vulnerabilidades (CVE), quantidade de aplicações afetadas',
        filters=(_SAME_SCOPE, _POLICY, _OPEN),
        lines=_items('top', 'vulnerability_id', 'vulnerability_id', 'applications'), totals=(('total', 'Findings'),)),
    'sca.policy.open.by_dependency_mode': Guide(
        Category.APPLICABLE, path='SCA (Policy) → findings abertos por dependência direta/transitiva',
        filters=(_SAME_SCOPE, _POLICY, _OPEN), lines=_items('items', 'mode', 'mode', 'findings'),
        totals=(('total', 'Total'),)),
    'sca.policy.summary.components': Guide(
        Category.APPLICABLE, path='Summary Report da Policy → Software Composition Analysis (componentes de '
                                  'terceiros; componentes que violam a política)',
        filters=(_SAME_SCOPE, _POLICY, 'Build mais recente'),
        lines=('fields', (('third_party_components', 'Componentes de terceiros'),
                          ('components_violated_policy', 'Componentes que violam a política')))),
    'sca.agent.linked_projects': Guide(
        Category.APPLICABLE, path='Perfil da aplicação → projetos do SCA Agent vinculados',
        filters=(_SAME_SCOPE,), lines=('fields', (('applications_with_linked_projects', 'Aplicações com projetos'),
                                                  ('linked_projects', 'Projetos vinculados')))),
    'sca.policy.open.at_period_end': Guide(Category.NOT_APPLICABLE, reason=_NA_HISTORY),
    'sca.policy.new_in_period': Guide(Category.NOT_APPLICABLE, reason='first_found_date do SCA é ambíguo (publicação '
                                      'da vulnerabilidade × detecção): sem definição oficial equivalente'),
    'sca.agent.issues': Guide(Category.NOT_APPLICABLE, reason='Fonte fora da allowlist e não homologada; indicador '
                              'não calculado'),
    'scans.count': Guide(Category.BLOCKED_EXTERNAL, reason=_BLOCKED_REPORTING),
    'scans.covered_apps': Guide(Category.NOT_APPLICABLE, reason='O perfil só mostra o ÚLTIMO scan: um scan posterior '
                                'à competência oculta o do período (indeterminado por definição)'),
    # F12: fonte comprovada (relatório SCANS, um item por scan) bloqueada fora do projeto; quando a Reporting API for
    # habilitada e o valor coletado, passa a APPLICABLE (tela indicativa: Analytics → Scans, publicados no período).
    'apps.scanned': Guide(Category.BLOCKED_EXTERNAL, reason='Fonte = relatório SCANS da Reporting API (um item por '
                          'scan, data de publicação), HTTP 403 na conta de testes desde a F05; POST não repetido sem '
                          'mudança de permissão comprovada. O último scan do perfil não substitui a fonte'),
    'licenses.usage': Guide(Category.NOT_APPLICABLE, reason='Sem API de licenças; entrada manual justificada (F05)'),
}
assert set(GUIDES) == set(REGISTRY), 'guia de conferência deve cobrir exatamente o catálogo'


def _num(v: Any) -> int | float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def computed_lines(guide: Guide, value: Any) -> list[dict]:
    """Linhas comparáveis do valor EFETIVO do snapshot (`key`, `label`, `computed`). Nunca inventa linhas."""
    if value is None:
        return []
    kind = guide.lines[0]
    if kind == 'scalar':
        n = _num(value.get('count')) if isinstance(value, dict) else _num(value)
        return [] if n is None else [{'key': 'value', 'label': 'Valor', 'computed': n}]
    if not isinstance(value, dict):
        return []
    if kind == 'severity':
        return [{'key': k, 'label': label, 'computed': value[k]} for k, label in SEVERITY_LINES
                if _num(value.get(k)) is not None]
    if kind == 'fields':
        return [{'key': f, 'label': label, 'computed': value[f]} for f, label in guide.lines[1]
                if _num(value.get(f)) is not None]
    _, list_key, id_field, label_field, value_field = guide.lines
    out = []
    for item in value.get(list_key) or []:
        ident, n = item.get(id_field), _num(item.get(value_field))
        if ident is None or n is None:
            continue
        label = item.get(label_field)
        if label_field == 'filename' and item.get('version'):
            label = f'{label} {item["version"]}'
        if id_field == 'cwe_id':
            label = f'CWE-{ident}' + (f' {label}' if label else '')
        out.append({'key': f'{list_key}:{ident}', 'label': str(label if label is not None else ident),
                    'computed': n})
    out += [{'key': f, 'label': label, 'computed': value[f]} for f, label in guide.totals
            if _num(value.get(f)) is not None]
    return out


def public(metric_id: str) -> dict:
    g = GUIDES[metric_id]
    return {'category': g.category.value, 'reason': g.reason or None, 'path': g.path or None,
            'filters': list(g.filters), 'path_is_indicative': True}
