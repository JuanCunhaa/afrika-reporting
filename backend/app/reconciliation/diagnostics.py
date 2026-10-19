"""Diagnóstico automático de divergência (F11): para cada indicador aplicável, as verificações da ordem do PO §4
calculadas só a partir do que o snapshot já guarda (proveniência, cobertura, motivos, contrato) e da conferência.

Status de cada verificação: OK (evidência favorável), ATTENTION (pode explicar uma diferença — investigar primeiro),
INFO (o operador precisa reproduzir a mesma condição na tela) e NOT_APPLICABLE. Nada aqui altera snapshot, aprovação
ou conferência; nada é presumido quando o snapshot não traz a informação (fica ATTENTION com o motivo).
"""
from __future__ import annotations

from app.metrics.contracts import (Dedup, IdentityProof, MetricContract, ScanContext, SeverityCriterion,
                                   StatusCriterion, TemporalMode)
from app.orm import Competence, MetricSnapshot, SnapshotOrigin
from app.snapshots.values import loads

OK, ATTENTION, INFO, NA = 'OK', 'ATTENTION', 'INFO', 'NOT_APPLICABLE'
CHECKS = (
    ('universe', 'Mesmo universo de aplicações'),
    ('classification', 'BU, Teams e subclientes'),
    ('context', 'Policy (produção) / Sandbox (desenvolvimento)'),
    ('period', 'Competência, data e fuso'),
    ('status', 'Critério de aberto, mitigado e resolvido'),
    ('severity', 'Severidade'),
    ('completeness', 'Paginação e completude'),
    ('identity', 'Identidade e deduplicação'),
    ('origin', 'Origem do valor calculado'),
)
_LABELS = dict(CHECKS)


def _check(code: str, status: str, detail: str) -> dict:
    return {'code': code, 'label': _LABELS[code], 'status': status, 'detail': detail}


def _reason_codes(snap: MetricSnapshot) -> set[str]:
    return {r.get('code') for r in loads(snap.source_reasons_json) or [] if isinstance(r, dict)}


def diagnose(comp: Competence, contract: MetricContract, snap: MetricSnapshot | None, collected_on: str | None,
             conference: dict | None) -> list[dict]:
    if snap is None:
        return [_check('origin', ATTENTION, 'Revisão sem snapshot deste indicador: nada a diagnosticar')]
    prov = loads(snap.provenance_json) or {}
    cov = prov.get('coverage') or {}
    reasons = _reason_codes(snap)
    scope_refs = loads(snap.scope_refs_json) or []
    out = []

    # 1. universo
    apps = cov.get('applications')
    if apps is None:
        out.append(_check('universe', ATTENTION, 'Snapshot sem contagem de aplicações do escopo (coleta antiga ou '
                                                 'manual): confirme a lista de aplicações na prévia do escopo'))
    else:
        visible = cov.get('total_available_in_tenant_view')
        extra = f'; visíveis à credencial de API: {visible}' if visible is not None else ''
        refs = ', '.join(f"{r['domain']} " + (f"v{r['version']}" if r.get('version') else str(r.get('status')))
                         for r in scope_refs if isinstance(r, dict) and r.get('domain')) or 'sem referência'
        out.append(_check('universe', INFO, f'{apps} aplicação(ões) no escopo do dono{extra} (escopos: {refs}). '
                                            'Na tela, filtre exatamente essas aplicações e use um usuário com a mesma '
                                            'visibilidade de Teams'))

    # 2. classificação
    kind = comp.owner_key.split(':', 1)[0]
    undetermined = cov.get('undetermined')
    missing = cov.get('missing_fields')
    flagged = sorted(c for c in reasons if c and ('undetermined' in c or 'missing' in c))
    if undetermined or missing or flagged:
        out.append(_check('classification', ATTENTION, f'Indeterminados no escopo: {undetermined or 0}; campos '
                                                       f'ausentes: {missing or {}}; motivos: {flagged or "—"}'))
    else:
        who = 'subcliente (critérios ∩ universo do cliente)' if kind == 'subclient' else 'cliente (universo)'
        out.append(_check('classification', OK, f'Dono = {who}; nenhum indeterminado registrado. Aplicação pode estar '
                                                'em mais de um subcliente'))

    # 3. contexto
    if contract.context == ScanContext.NOT_APPLICABLE:
        out.append(_check('context', NA, 'Indicador sem contexto de scan'))
    else:
        detail = {ScanContext.POLICY: 'Só Policy (produção), sem sandboxes',
                  ScanContext.SANDBOX: 'Só sandboxes (desenvolvimento), somando cada sandbox',
                  ScanContext.POLICY_AND_SANDBOX: 'Policy e sandboxes'}[contract.context]
        failed = cov.get('sandbox_listings_failed')
        if failed:
            out.append(_check('context', ATTENTION, f'{detail}; lista de sandboxes falhou em {failed} aplicação(ões)'))
        else:
            sb = cov.get('sandboxes')
            out.append(_check('context', INFO, detail + (f'; {sb} sandbox(es) coletado(s)' if sb is not None else '')
                              + f'; scan_type {prov.get("scan_type") or contract.scan_type.value}'))

    # 4. período
    checked = (conference or {}).get('checked_on')
    head = f'Competência {comp.label}, fuso {comp.timezone}, coleta em {collected_on or "—"}'
    if contract.temporal_mode == TemporalMode.CURRENT_STATE:
        if checked and checked != collected_on:
            out.append(_check('period', ATTENTION, f'{head}; estado ATUAL conferido em {checked}: a plataforma pode '
                                                   'ter mudado entre as datas'))
        else:
            out.append(_check('period', OK if checked else INFO, f'{head}; estado ATUAL: conferir no mesmo dia'))
    else:
        out.append(_check('period', INFO, f'{head}; eventos com data dentro da competência no fuso do cliente '
                                          '(a tela precisa usar o mesmo intervalo e fuso)'))

    # 5. status
    if contract.status_criterion == StatusCriterion.OPEN_EXCLUDING_APPROVED_MITIGATIONS:
        excl = cov.get('excluded_approved_mitigations')
        out.append(_check('status', INFO, 'Aberto = status OPEN sem mitigação APROVADA (proposta/rejeitada segue '
                                          'aberta)' + (f'; {excl} finding(s) excluído(s) por mitigação aprovada'
                                                       if excl is not None else '')))
    elif contract.status_criterion == StatusCriterion.ANY_STATUS:
        out.append(_check('status', INFO, 'Qualquer status (aberto, mitigado ou fechado ainda visível na API)'))
    elif contract.status_criterion == StatusCriterion.NOT_APPLICABLE:
        out.append(_check('status', NA, 'Indicador sem critério de status'))
    else:
        out.append(_check('status', INFO, f'Critério {contract.status_criterion.value}'))

    # 6. severidade
    if contract.severity_criterion == SeverityCriterion.NOT_APPLICABLE:
        out.append(_check('severity', NA, 'Indicador sem severidade'))
    elif 'severity_missing' in reasons:
        out.append(_check('severity', ATTENTION, 'Há findings sem severidade informada'))
    else:
        out.append(_check('severity', OK, 'Severidade original da Findings API (5 Very High … 0 Informational); '
                                          'severidade customizada na tela não é comparável'))

    # 7. completude
    expected = cov.get('contexts_expected')
    complete = cov.get('contexts_complete')
    retried = cov.get('contexts_retried')
    if snap.source_status != 'VALIDATED':
        out.append(_check('completeness', ATTENTION, f'Coleta {snap.source_status or "sem status"}: o valor não '
                                                     'vem de uma coleta completa'))
    elif expected is not None and complete is not None and complete != expected:
        out.append(_check('completeness', ATTENTION, f'{complete}/{expected} contextos completos'))
    else:
        detail = (f'{complete}/{expected} contextos completos (total anunciado pela paginação = itens recebidos)'
                  if expected is not None else 'Coleta VALIDATED')
        out.append(_check('completeness', OK, detail + (f'; {retried} contexto(s) com nova tentativa'
                                                        if retried else '')))

    # 8. identidade
    if contract.identity_proof == IdentityProof.NOT_PROVEN:
        out.append(_check('identity', ATTENTION, f'Deduplicação {contract.dedup.value} com identidade NÃO '
                                                 'comprovada'))
    elif contract.dedup == Dedup.NONE:
        out.append(_check('identity', INFO, 'Sem deduplicação: cada finding listado pela API conta 1 (SCA não tem '
                                            'issue_id); nomes nunca são usados como identidade'))
    else:
        out.append(_check('identity', OK, f'Deduplicação {contract.dedup.value} ({contract.identity_proof.value})'))

    # 9. origem
    if snap.origin == SnapshotOrigin.MANUAL.value:
        out.append(_check('origin', ATTENTION, 'Valor efetivo MANUAL: conferir não homologa o cálculo'))
    else:
        out.append(_check('origin', OK, f'Valor calculado pela coleta ({snap.origin}), lido do snapshot'))
    return out


def summary(checks: list[dict]) -> dict:
    return {'attention': [c['code'] for c in checks if c['status'] == ATTENTION],
            'counts': {s: sum(c['status'] == s for c in checks) for s in (OK, ATTENTION, INFO, NA)}}
