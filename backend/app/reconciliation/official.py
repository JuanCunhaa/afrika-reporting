"""Definições oficiais, prioridade e diferenças conhecidas de definição por indicador APLICÁVEL (F11).

Fonte: documentação pública da Veracode consultada em 2026-10-19 (links em `docs`). Citações entre aspas são
literais da documentação; o restante é a leitura do Afrika. Onde a documentação consultada NÃO define o número, a
definição fica vazia (`''`) — nada é presumido. As telas continuam INDICATIVAS (o agente não acessa o portal): o
operador confirma o local exato ao conferir e o registra na evidência.

`hints` = diferenças de definição já conhecidas entre o dashboard e o contrato do Afrika; são os primeiros pontos a
verificar numa divergência (nunca justificam alterar o número sem prova).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.reconciliation.guide import GUIDES, Category

DOC_APPS_EXPLORE = 'https://docs.veracode.com/r/Applications_explore_data_dictionary'
DOC_FINDINGS_EXPLORE = 'https://docs.veracode.com/r/Findings_explore_data_dictionary'
DOC_POLICY = 'https://docs.veracode.com/r/policy_understand'
DOC_FINDINGS_API = 'https://docs.veracode.com/r/c_findings_v2_intro'
DOC_SUMMARY_API = 'https://docs.veracode.com/r/c_rest_summary_report_intro'
ANALYTICS = 'Manage risk → Analytics → Explore your data'

# Ordem de prioridade da conferência (ordem do PO, F11 §2). A prioridade 9 não tem indicador aplicável (ver GAPS).
PRIORITIES: dict[int, str] = {
    1: 'Total de aplicações', 2: 'Aplicações por BU e Team', 3: 'Conformidade de política',
    4: 'SAST por severidade em produção', 5: 'SAST por severidade em desenvolvimento',
    6: 'SCA por severidade em produção', 7: 'SCA por severidade em desenvolvimento', 8: 'Linhas de código',
    9: 'Aplicações com scans',
}
PRIORITY_GAPS: dict[int, str] = {
    9: ('Nenhum indicador aplicável: `scans.covered_apps` é NOT_APPLICABLE (scan publicado DENTRO da competência; o '
        'perfil só mostra o último scan). O equivalente do dashboard ("Application Scanned (Yes/No)", estado atual) '
        'exige contrato novo — proposta em docs/F11_METRIC_HOMOLOGATION.md, não implementada sem decisão do PO'),
}

_OPEN_DEF = ('Findings explore: Finding Status "Values are Open or Closed"; Resolution and Mitigation Status '
             '"Approved, Proposed, Automated, or None"; Custom Severity Name "Informational, Very Low, Low, Medium, '
             'High, or Very High"; "Policy or Sandbox Scan: Determines if the finding is in a policy or sandbox '
             'scan." Findings API: "open and mitigated findings associated with applications and development '
             'sandboxes".')
_SEVERITY_HINTS = (
    'Severidade: o Afrika usa a severidade da Findings API (0–5); se o cliente usa Custom Severity, o Analytics pode '
    'agrupar pela severidade customizada',
    'Mitigação: só a APROVADA sai do aberto no Afrika; Proposta/Rejeitada continua aberta — confira o filtro de '
    'mitigação da tela',
    'Fechados: segundo a comunidade Veracode (não confirmado na documentação oficial), a Findings API pode omitir '
    'findings fechados por rescan; filtro "Closed" ou "todos os status" na tela não é comparável',
)
_SCOPE_HINT = ('Visibilidade: a credencial de API e o usuário do portal precisam enxergar os mesmos Teams/aplicações '
               '(conta restrita a Teams vê menos aplicações)')


@dataclass(frozen=True)
class Official:
    priority: int | None = None
    definition: str = ''  # '' = a documentação consultada não define este número
    docs: tuple[str, ...] = ()
    analytics: str = ''   # local alternativo no Veracode Analytics (indicativo)
    hints: tuple[str, ...] = ()


OFFICIAL: dict[str, Official] = {
    'apps.total': Official(
        1, 'Perfil de aplicação do Veracode Platform; o número é a quantidade de perfis do escopo (o Analytics não '
           'publica uma definição de "total de aplicações").', (DOC_APPS_EXPLORE,),
        f'{ANALYTICS} → Applications (contagem de aplicações)', (_SCOPE_HINT,
                                                                'Aplicações inativas ficam fora do escopo por '
                                                                'padrão no Afrika (F03)')),
    'apps.by_business_unit': Official(
        2, 'Applications explore — Business Unit: "The name of the business unit."', (DOC_APPS_EXPLORE,),
        f'{ANALYTICS} → Applications, dimensão Business Unit',
        (_SCOPE_HINT, 'O Afrika agrupa pelo GUID da BU (nome não é identidade); BUs homônimas aparecem separadas')),
    'apps.by_team': Official(
        2, 'Applications explore — Teams List: "The list of teams and security lead teams who need access to the '
           'specific applications and scan results."', (DOC_APPS_EXPLORE,),
        f'{ANALYTICS} → Applications, dimensão Teams List',
        (_SCOPE_HINT, 'Aplicação com vários Teams conta em cada Team (soma ≥ total)',
         'Teams List do Analytics inclui "security lead teams"; o Afrika usa os Teams do perfil da aplicação')),
    'apps.without_team': Official(
        None, '', (DOC_APPS_EXPLORE,), f'{ANALYTICS} → Applications, Teams List vazia',
        (_SCOPE_HINT, 'Teams ausentes no retorno da API ≠ Teams vazios (ausente ⇒ INCOMPLETE no Afrika)')),
    'apps.multiple_teams': Official(
        None, '', (DOC_APPS_EXPLORE,), f'{ANALYTICS} → Applications, Teams List com 2 ou mais Teams',
        (_SCOPE_HINT, 'Teams List do Analytics inclui "security lead teams"')),
    'apps.by_policy_compliance': Official(
        3, 'Policy: Passed — atende regras, scans exigidos e prazo; Did not pass — scans ausentes, nível não '
           'atingido ou findings fora do prazo; Conditional pass — findings de política ainda no prazo (todos os '
           'scans de sandbox também); Not assessed — nenhum scan publicado. Applications explore: "Calculating..., '
           'Conditional Pass, Did Not Pass, Pass, or Not Assessed."', (DOC_POLICY, DOC_APPS_EXPLORE),
        f'{ANALYTICS} → Applications, dimensão Policy Compliance Status',
        ('O Analytics usa "Pass" (não "Passed") e tem o estado transitório "Calculating..." — sem equivalente na API',
         'O filtro policy_compliance da API REST aceita só PASSED, DID_NOT_PASS e NOT_ASSESSED; compare pelo rótulo '
         'do perfil, não pelo filtro', 'Só a política da Policy (produção); sandbox não entra')),
    'apps.loc.total': Official(
        8, '', (DOC_SUMMARY_API,), '',
        ('A documentação consultada não define LOC: valor do Summary Report (último build estático da Policy) — '
         'scan de sandbox ou módulos não selecionados mudam o número',)),
    'sast.policy.open.by_severity': Official(
        4, _OPEN_DEF, (DOC_FINDINGS_EXPLORE, DOC_FINDINGS_API),
        f'{ANALYTICS} → Findings, Policy or Sandbox Scan = Policy, Finding Status = Open, por severidade',
        _SEVERITY_HINTS + ('Analytics: "Count of Flaws Application" conta só findings únicos casados à política no '
                           'contexto Policy; "Total Number of Flaws - Application" conta de outra forma',)),
    'sast.sandbox.open.by_severity': Official(
        5, _OPEN_DEF + ' Total Number of Sandbox Flaws: "The total number of findings by sandbox."',
        (DOC_FINDINGS_EXPLORE, DOC_FINDINGS_API),
        f'{ANALYTICS} → Findings, Policy or Sandbox Scan = Sandbox, Finding Status = Open, por severidade',
        _SEVERITY_HINTS + ('O Afrika SOMA ocorrências entre sandboxes (o mesmo finding em 2 sandboxes conta 2)',)),
    'sast.policy.open.by_cwe': Official(
        None, 'Findings explore — CWE ID: "The ID and the name of the common weakness enumeration (CWE) found after '
              'the application was scanned."', (DOC_FINDINGS_EXPLORE,), f'{ANALYTICS} → Findings, dimensão CWE ID',
        _SEVERITY_HINTS[1:] + ('Top 10 com desempate do Afrika (não oficial): compare CWE a CWE',)),
    'sast.policy.open.top_applications': Official(
        None, '', (DOC_FINDINGS_EXPLORE,), f'{ANALYTICS} → Findings, por aplicação',
        _SEVERITY_HINTS[1:] + ('Top 10 com desempate do Afrika (não oficial)',)),
    'sast.policy.new_in_period.by_severity': Official(
        None, 'Findings explore — First Found Date: "Very first overall occurrence of the finding in a given '
              'context. In most cases, First Found in Application Date should be used."', (DOC_FINDINGS_EXPLORE,),
        f'{ANALYTICS} → Findings, First Found Date na competência',
        ('O Afrika usa finding_status.first_found_date da Findings API (por contexto); o Analytics recomenda "First '
         'Found in Application Date" — escolher a MESMA data na tela', 'Competência no fuso do cliente',
         'Qualquer status (inclui fechados ainda visíveis na Findings API)')),
    'sast.policy.open.by_first_found_month': Official(
        None, 'Findings explore — First Found Date (ver acima).', (DOC_FINDINGS_EXPLORE,),
        f'{ANALYTICS} → Findings, Finding Status = Open, por mês de First Found Date',
        ('Mesma ressalva de First Found Date × First Found in Application Date', 'Mês no fuso do cliente')),
    'sast.policy.summary.by_severity': Official(
        None, '', (DOC_SUMMARY_API,), '',
        ('A documentação consultada não diz se mitigados entram na contagem do Summary Report',)),
    'sca.policy.open.by_severity': Official(
        6, _OPEN_DEF + ' Findings API: "You cannot get SCA findings in combination with other finding types."',
        (DOC_FINDINGS_EXPLORE, DOC_FINDINGS_API),
        'Perfil da aplicação → Software Composition Analysis (Policy), vulnerabilidades por severidade',
        _SEVERITY_HINTS + ('O Afrika conta FINDINGS SCA (vulnerabilidade × componente) da Findings API, sem '
                           'deduplicação; telas que contam bibliotecas ou CVEs distintos não são comparáveis',
                           'Findings SCA reais têm campo `count` (semântica não documentada; distribuição medida '
                           'no diagnóstico F11)')),
    'sca.sandbox.open.by_severity': Official(
        7, _OPEN_DEF, (DOC_FINDINGS_EXPLORE, DOC_FINDINGS_API),
        'Perfil da aplicação → Sandboxes → cada sandbox → SCA, por severidade',
        _SEVERITY_HINTS + ('O Afrika SOMA ocorrências entre sandboxes',)),
    'sca.policy.open.top_components': Official(
        None, 'Findings explore — Component ID: "ID that Veracode gives to each unique component."; Component Name: '
              '"Name of the library component, including version."', (DOC_FINDINGS_EXPLORE,),
        f'{ANALYTICS} → Findings, dimensão Component Name', ('Top 10 com desempate do Afrika (não oficial)',)),
    'sca.policy.open.top_vulnerabilities': Official(
        None, '', (DOC_FINDINGS_EXPLORE,), '', ('Conta aplicações afetadas por CVE, não findings',)),
    'sca.policy.open.by_dependency_mode': Official(
        None, '', (DOC_FINDINGS_API,), '', ('Direta/transitiva pelo atributo da Findings API',)),
    'sca.policy.summary.components': Official(
        None, '', (DOC_SUMMARY_API,), '', ('Componentes ≠ vulnerabilidades: não comparar com a Findings SCA',)),
    'sca.agent.linked_projects': Official(None, '', (), '', ()),
}
assert set(OFFICIAL) == {m for m, g in GUIDES.items() if g.category is Category.APPLICABLE}, \
    'definição oficial deve cobrir exatamente os indicadores aplicáveis'


def public(metric_id: str) -> dict | None:
    o = OFFICIAL.get(metric_id)
    if o is None:
        return None
    return {'priority': o.priority, 'priority_label': PRIORITIES.get(o.priority) if o.priority else None,
            'definition': o.definition or None, 'definition_documented': bool(o.definition),
            'docs': list(o.docs), 'analytics_location': o.analytics or None, 'known_differences': list(o.hints)}
