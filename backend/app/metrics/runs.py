"""Execuções de métricas (F04): iniciadas explicitamente, em segundo plano, canceláveis, só em memória.

- O resultado guarda APENAS agregados e metadados (nenhum finding individual); some quando o processo reinicia.
- Persistência/aprovação de snapshots é da F05: aqui só o contrato (`input_hash`, versões de contrato e escopo).
- Limite de execuções simultâneas e de execuções retidas (as mais antigas finalizadas são descartadas).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum

from app.metrics import collector, engine
from app.metrics.competence import Competence
from app.metrics.population import Inputs, PopulationStatus, resolve_population
from app.metrics.registry import CONTRACTS, REGISTRY
from app.veracode import adapters
from app.veracode.discovery import DiscoveryService
from app.veracode.errors import VeracodeError

logger = logging.getLogger('afrika.metrics')
ENGINE_VERSION = 'F04-metrics-1'


class RunStatus(StrEnum):
    PENDING = 'pending'
    RUNNING = 'running'
    DONE = 'done'
    CANCELLED = 'cancelled'
    FAILED = 'failed'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Run:
    id: str
    owner: dict
    competence: Competence
    status: RunStatus = RunStatus.PENDING
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    progress: dict = field(default_factory=lambda: {'stage': 'pending', 'applications_done': 0,
                                                    'applications_total': None})
    result: dict | None = None
    error: dict | None = None
    task: asyncio.Task | None = None

    @property
    def finished(self) -> bool:
        return self.status in (RunStatus.DONE, RunStatus.CANCELLED, RunStatus.FAILED)

    def public(self, *, with_result: bool = True) -> dict:
        out = {'run_id': self.id, 'status': self.status.value, 'owner': self.owner,
               'competence': self.competence.as_dict(), 'created_at': self.created_at,
               'started_at': self.started_at, 'finished_at': self.finished_at, 'progress': dict(self.progress),
               'error': self.error}
        if with_result:
            out['result'] = self.result
        else:
            out['summary'] = (self.result or {}).get('summary')
        return out


def input_hash(owner: dict, competence: Competence, scope_refs: list[dict]) -> str:
    payload = {'owner': [owner['kind'], owner['id']], 'competence': competence.label,
               'utc_offset': competence.utc_offset, 'scope_refs': scope_refs,
               'contracts': {c.metric_id: c.version for c in CONTRACTS}, 'engine': ENGINE_VERSION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _contract_head(metric_id: str) -> dict:
    c = REGISTRY[metric_id]
    return {'name': c.name, 'description': c.description, 'domain': c.domain.value, 'source': c.source.value,
            'endpoint': c.endpoint, 'context': c.context.value, 'scan_type': c.scan_type.value,
            'shape': c.shape.value, 'unit': c.unit.value, 'support': c.support.value,
            'homologation': c.homologation.value, 'limitations': list(c.limitations)}


class RunManager:
    def __init__(self, service: DiscoveryService, *, max_runs: int = 50, max_active: int = 3):
        self.service = service
        self.max_runs = max_runs
        self.max_active = max_active
        self._runs: OrderedDict[str, Run] = OrderedDict()

    def active(self) -> int:
        return sum(not r.finished for r in self._runs.values())

    def start(self, inputs: Inputs, competence: Competence) -> Run:
        owner = {'kind': inputs.kind, 'id': str(inputs.owner_id), 'name': inputs.owner_name,
                 'client_id': str(inputs.client_ctx.client_id)}
        run = Run(str(uuid.uuid4()), owner, competence)
        self._runs[run.id] = run
        self._evict()
        run.task = asyncio.get_running_loop().create_task(self._execute(run, inputs))
        run.task.add_done_callback(lambda t: self._cancelled_before_start(run, t))
        logger.info('métricas execução=%s dono=%s:%s competência=%s iniciada', run.id, inputs.kind,
                    inputs.owner_id, competence.label)
        return run

    @staticmethod
    def _cancelled_before_start(run: Run, task: asyncio.Task) -> None:
        if task.cancelled() and not run.finished:  # cancelada antes de a corrotina começar
            run.status, run.finished_at = RunStatus.CANCELLED, _now()
            run.error = {'code': 'cancelled', 'message': 'Execução cancelada: nenhum indicador publicado'}
            run.progress['stage'] = run.status.value

    def _evict(self) -> None:
        while len(self._runs) > self.max_runs:
            victim = next((k for k, r in self._runs.items() if r.finished), None)
            if victim is None:
                break
            self._runs.pop(victim)

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def list(self) -> list[Run]:
        return list(reversed(self._runs.values()))

    def cancel(self, run_id: str) -> Run | None:
        run = self._runs.get(run_id)
        if run is not None and not run.finished and run.task is not None:
            run.task.cancel()
        return run

    async def aclose(self) -> None:
        tasks = [r.task for r in self._runs.values() if r.task and not r.task.done()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute(self, run: Run, inputs: Inputs) -> None:
        run.status, run.started_at = RunStatus.RUNNING, _now()
        try:
            run.progress['stage'] = 'population'
            pop = await resolve_population(self.service, inputs)
            outcome = None
            if pop.status in (PopulationStatus.OK, PopulationStatus.INCOMPLETE):
                limit = self.service.settings.metrics_max_applications
                run.progress.update(stage='findings', applications_total=len(pop.applications))
                if len(pop.applications) > limit:
                    outcome = collector.CollectionOutcome(
                        skipped_reason=f'população acima do limite configurado ({len(pop.applications)} > {limit})')
                else:
                    try:
                        outcome = await collector.collect(
                            self.service, pop.ctx, pop.applications,
                            progress=lambda d, t: run.progress.update(applications_done=d, applications_total=t))
                    except VeracodeError as exc:
                        outcome = collector.CollectionOutcome(skipped_reason=exc.code)
            collected_at = _now()
            run.progress['stage'] = 'computing'
            ctx = engine.Context(run.competence, pop, outcome, inputs.finding_rules, collected_at, inputs.kind)
            metrics = engine.compute_all(ctx)
            run.result = {
                'owner': run.owner,
                'competence': run.competence.as_dict(),
                'collected_at': collected_at,
                'applications_collected_at': pop.collected_at,
                'connection': None if pop.ctx is None else {
                    'connection_source': pop.ctx.connection_source,
                    **({} if pop.ctx.connection_id is None else {
                        'id': str(pop.ctx.connection_id), 'name': pop.ctx.connection_name,
                        'region': pop.ctx.region})},
                'population': {'status': pop.status.value, 'reasons': [r.as_dict() for r in pop.reasons],
                               'applications': len(pop.applications), 'total_available': pop.total_available,
                               'undetermined': pop.undetermined, 'missing_fields': pop.missing_fields,
                               'collections': pop.collections},
                'collection': outcome.summary() if outcome else None,
                'limits': {'max_requests': self.service.settings.metrics_max_requests,
                           'timeout_seconds': self.service.settings.metrics_timeout,
                           'max_applications': self.service.settings.metrics_max_applications},
                'provenance': {'run_id': run.id, 'engine': ENGINE_VERSION, 'scope_refs': pop.scope_refs,
                               'endpoints': [f'GET {adapters.APPLICATIONS}', f'GET {adapters.SANDBOXES}',
                                             f'GET {adapters.FINDINGS}?scan_type=STATIC|SCA[&context=sandbox]'],
                               'contracts': {c.metric_id: c.version for c in CONTRACTS},
                               'input_hash': input_hash(run.owner, run.competence, pop.scope_refs),
                               'snapshot': 'não persistido (F05)'},
                'summary': dict(Counter(m.status.value for m in metrics)),
                'metrics': [{**m.as_dict(), **_contract_head(m.metric_id)} for m in metrics],
            }
            run.status = RunStatus.DONE
        except asyncio.CancelledError:
            run.status = RunStatus.CANCELLED
            run.error = {'code': 'cancelled', 'message': 'Execução cancelada: nenhum indicador publicado'}
        except Exception as exc:  # noqa: BLE001 - registrar só o tipo; nunca mensagens com dados
            logger.error('métricas execução=%s falhou: %s', run.id, type(exc).__name__)
            run.status = RunStatus.FAILED
            run.error = {'code': 'internal_error', 'message': 'Falha interna na execução de métricas'}
        finally:
            run.finished_at = _now()
            run.progress['stage'] = run.status.value
            logger.info('métricas execução=%s status=%s', run.id, run.status.value)
