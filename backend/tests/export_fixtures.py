"""F07 — dados SINTÉTICOS para os testes de exportação (nenhum dado real, nenhuma Veracode).

`full_values` cobre todos os indicadores do `afrika-modelo@2` (inclusive distribuições e rankings), para a
apresentação ficar PRONTA (sem bloqueios) e todos os tipos de objeto aparecerem no PPTX/PDF.
"""
from __future__ import annotations

from test_presentations import Env, sev

SAST, SCA = 'sast.policy.open.by_severity', 'sca.policy.open.by_severity'


def full_values(i: int = 0, *, primary: bool = True) -> dict:
    v = {'apps.total': 140 + i, 'apps.without_team': 7, 'apps.multiple_teams': 3, 'apps.unclassified': 2,
         'apps.loc.total': 2_400_000 + i * 35_000,
         SAST: sev(2, 7, 23 + i, 9, 3, 1, 1), SCA: sev(1, 4, 11 + i, 5, 2, 1, 0),
         'sast.sandbox.open.by_severity': sev(1, 3, 8, 6, 2, 0, 1),
         'sast.open.distinct': sev(2, 7, 18 + i, 11, 3, 1, 0), 'sca.open.distinct': sev(1, 5, 9, 6, 2, 1, 0),
         'sast.policy.new_in_period.by_severity': sev(0, 1, 4 + i, 2, 1, 0, 0)}
    if primary:
        v['apps.by_business_unit'] = {
            'items': [{'business_unit_id': f'ab{k}', 'name': f'Unidade {n}', 'applications': 41 - k * 7}
                      for k, n in enumerate(('Norte', 'Sul', 'Leste', 'Oeste', 'Centro'))],
            'unknown': 0, 'distinct_applications': 135}
        v['sast.policy.open.top_applications'] = {
            'top': [{'application_guid': f'ag{k}', 'name': f'Aplicação Sintética {k + 1:02d}', 'findings': 64 - k * 5}
                    for k in range(12)], 'total': 512}
        v['sast.policy.open.by_cwe'] = {'top': [{'cwe_id': c, 'findings': 38 - k * 5}
                                                for k, c in enumerate((79, 89, 117, 327, 73, 601))], 'others': 12}
        v['sca.policy.open.top_components'] = {
            'top': [{'component_id': f'ac{k}', 'filename': f'biblioteca-sintetica-{k + 1}.jar', 'version': f'2.{k}.1',
                     'findings': 27 - k * 2, 'applications': 9 - (k % 5)} for k in range(10)]}
        v['sca.policy.open.top_vulnerabilities'] = {
            'top': [{'vulnerability_id': f'VULN-SINT-{k + 1:03d}', 'applications': 12 - k, 'findings': 30 - k * 2,
                     'max_severity': ('VERY_HIGH', 'HIGH', 'MEDIUM')[k % 3]} for k in range(10)]}
    return v


def ready_presentation(env: Env, owner_id: str, *, kind: str = 'client', template: str = 'afrika-modelo',
                       version: int = 2, previous: tuple[str, ...] = ('2026-08',), values: dict | None = None,
                       **kw) -> tuple[str, dict, dict]:
    """Competência 2026-09 aprovada com todos os indicadores + meses anteriores aprovados (lacunas nos demais).
    `values` substitui indicadores da competência principal (ex.: nomes sintéticos longos)."""
    for label in previous:
        env.approved(owner_id, label, full_values(-1, primary=False), kind)
    cid = env.competence(owner_id, '2026-09', kind)
    env.fill(cid, 1, {**full_values(), **(values or {})})
    env.approve(cid, 1, ['apps.total'])
    p = env.present(cid, template_key=template, template_version=version, **kw)
    return cid, p, env.view(p['id'])
