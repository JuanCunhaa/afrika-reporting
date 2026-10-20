"""Adaptador da Reporting API (F05): gerar relatório (POST autorizado), acompanhar o processamento e ler o resultado.

Fluxo (especificação oficial 1.12.0, ver `reporting_policy`):
1. `POST /appsec/v1/analytics/report` com filtros validados -> id (UUID) + status;
2. `GET  /appsec/v1/analytics/report/{id}?page=0` até COMPLETED/FAILED — polling LIMITADO (intervalo crescente,
   número máximo de consultas e prazo global);
3. `GET  …?page=N` para as demais páginas (`page_metadata.total_pages`), até o limite configurado.

Minimização: cada item é reduzido IMEDIATAMENTE a campos de agregação (tipo de scan, contexto, status, severidade,
datas, id numérico da aplicação). Descrições, caminhos de arquivo, nomes de usuários, comentários de mitigação e o
solicitante do relatório são descartados; nada é gravado em disco. Os agregados são EXPLORATÓRIOS: não alimentam o
catálogo de indicadores (sem contrato/homologação) e não são equivalentes a números de dashboard.
Cancelamento: interrompe o polling/leitura localmente; a API não oferece cancelamento — o relatório gerado expira
sozinho na Veracode (`report_expiration_date`). Datas dos itens estão em EDT segundo a especificação.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections import Counter, OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum

from app.veracode.credentials import Credentials
from app.veracode.errors import VeracodeError
from app.veracode.http import CollectionRun, VeracodeHttpPool
from app.veracode.reporting_policy import GENERATION_PATH, ReportRequest
from app.veracode.settings import VeracodeSettings

logger = logging.getLogger('afrika.veracode.reporting')
REPORT_STATUSES = ('QUEUED', 'SUBMITTED', 'PROCESSING', 'COMPLETED', 'FAILED')
_UUID = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
_ITEMS_KEY = {'FINDINGS': 'findings', 'SCANS': 'scans'}
# Campos mantidos por item (todo o resto é descartado na leitura).
KEEP_FIELDS = {
    'FINDINGS': ('app_id', 'scan_type', 'policy_sandbox', 'status', 'severity', 'found_date', 'resolved_date',
                 'fixed_date', 'reopened_date', 'last_updated_date'),
    # F12: + scan_id (deduplicação entre páginas) e promoted_scan (sandbox promovido) para `apps.scanned`.
    'SCANS': ('app_id', 'scan_id', 'scan_type', 'policy_sandbox', 'scan_state', 'submitted', 'published',
              'last_updated_date', 'most_recent_scan', 'first_scan', 'promoted_scan'),
}
_META_DATES = ('date_report_requested', 'date_report_completed', 'report_expiration_date', 'data_refresh_date')


@dataclass(frozen=True)
class PageMeta:
    number: int
    size: int
    total_elements: int
    total_pages: int


@dataclass(frozen=True)
class ReportStatus:
    id: str
    status: str
    report_type: str | None
    dates: dict
    page: PageMeta | None
    items: list[dict]
    envelope: str  # 'embedded' (especificação) | 'top_level' (tolerado; registrado no diagnóstico)


def _scalar(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        return v[:40]
    return None


def minimize(report_type: str, item: dict) -> dict:
    return {k: _scalar(item.get(k)) for k in KEEP_FIELDS[report_type] if k in item}


def _page_meta(raw) -> PageMeta | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise VeracodeError('invalid_response')
    vals = [raw.get(k) for k in ('number', 'size', 'total_elements', 'total_pages')]
    if all(v is None for v in vals):
        return None  # EmptyPageMetadata (relatório ainda em processamento)
    if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in vals):
        raise VeracodeError('invalid_response')
    return PageMeta(*vals)


def parse_report(data: dict, report_type: str) -> ReportStatus:
    emb, envelope = data.get('_embedded'), 'embedded'
    if not isinstance(emb, dict):
        if 'id' not in data:
            raise VeracodeError('invalid_response')
        emb, envelope = data, 'top_level'
    rid, status = emb.get('id'), emb.get('status')
    if not isinstance(rid, str) or not _UUID.fullmatch(rid) or status not in REPORT_STATUSES:
        raise VeracodeError('invalid_response')
    rtype = emb.get('report_type')
    if rtype is not None and str(rtype).upper() != report_type:
        raise VeracodeError('invalid_response')
    raw_items = emb.get(_ITEMS_KEY[report_type])
    if raw_items is None:
        raw_items = []
    if not isinstance(raw_items, list) or not all(isinstance(i, dict) for i in raw_items):
        raise VeracodeError('invalid_response')
    dates = {k: emb.get(k) if isinstance(emb.get(k), str) else None for k in _META_DATES}
    return ReportStatus(rid.lower(), status, rtype, dates, _page_meta(emb.get('page_metadata')),
                        [minimize(report_type, i) for i in raw_items], envelope)


def aggregate(report_type: str, items: list[dict]) -> dict:
    """Contagens exploratórias (não homologadas) sobre os itens minimizados."""
    def by(key):
        return dict(sorted(Counter(str(i.get(key)) if i.get(key) is not None else 'NONE' for i in items).items()))

    apps = {i.get('app_id') for i in items if i.get('app_id') is not None}
    out = {'items': len(items), 'distinct_applications': len(apps), 'by_scan_type': by('scan_type'),
           'by_policy_sandbox': by('policy_sandbox')}
    if report_type == 'FINDINGS':
        out.update(by_status=by('status'), by_severity=by('severity'),
                   with_resolved_date=sum(bool(i.get('resolved_date')) for i in items),
                   with_fixed_date=sum(bool(i.get('fixed_date')) for i in items),
                   with_reopened_date=sum(bool(i.get('reopened_date')) for i in items))
    else:
        out.update(by_scan_state=by('scan_state'), published=sum(bool(i.get('published')) for i in items),
                   most_recent=sum(i.get('most_recent_scan') is True for i in items))
    return out


class ReportingClient:
    def __init__(self, pool: VeracodeHttpPool, creds: Credentials, region: str, *, sleep=asyncio.sleep,
                 clock: Callable[[], float] = time.monotonic):
        s = pool.settings
        self.settings = s
        self._sleep = sleep
        self._clock = clock
        self.run = CollectionRun(pool, creds, region, sleep=sleep, clock=clock,
                                 max_requests=s.reporting_max_polls + s.reporting_max_pages + 2 * (s.max_retries + 1),
                                 timeout=s.reporting_timeout)

    async def submit(self, request: ReportRequest) -> ReportStatus:
        data = await self.run.post_json(GENERATION_PATH, request.body(), label='reporting.generate')
        return parse_report(data, request.report_type)

    async def status(self, report_id: str, report_type: str, page: int = 0) -> ReportStatus:
        data = await self.run.get_json(f'{GENERATION_PATH}/{report_id}', {'page': page}, label='reporting.status')
        st = parse_report(data, report_type)
        if st.id != report_id:
            raise VeracodeError('invalid_response')
        return st

    async def execute(self, request: ReportRequest, progress: Callable[[dict], None]) -> dict:
        items, out = await self.fetch_items(request, progress)
        out.update(aggregates=aggregate(request.report_type, items),
                   aggregates_status='EXPLORATORY_NOT_HOMOLOGATED' if out['complete'] else 'INCOMPLETE',
                   caveats=['Agregados exploratórios: não são indicadores do catálogo nem números de dashboard',
                            'Datas dos itens em EDT segundo a especificação; não usadas para competência',
                            'Itens individuais descartados após a contagem (nada persistido)'])
        return out

    async def fetch_items(self, request: ReportRequest, progress: Callable[[dict], None]) -> tuple[list[dict], dict]:
        """Gera (1 POST), acompanha e lê todas as páginas. Itens JÁ minimizados; ficam só em memória."""
        s = self.settings
        st = await self.submit(request)
        progress({'stage': 'processing', 'report_id': st.id, 'veracode_status': st.status, 'envelope': st.envelope,
                  **st.dates})
        terminal = ('COMPLETED', 'FAILED')
        polls, interval = 0, s.reporting_poll_interval
        while True:  # o resultado sempre vem do GET (ao menos uma consulta), nunca da resposta do POST
            if polls >= s.reporting_max_polls:
                raise VeracodeError('report_poll_limit')
            if polls > 0 or st.status not in terminal:
                if self.run.remaining() <= interval:
                    raise VeracodeError('deadline_exceeded')
                await self._sleep(interval)
                interval = min(interval * 1.5, s.reporting_poll_max_interval)
            st = await self.status(st.id, request.report_type)
            polls += 1
            progress({'polls': polls, 'veracode_status': st.status, **st.dates})
            if st.status in terminal:
                break
        if st.status == 'FAILED':
            raise VeracodeError('report_failed')
        items = list(st.items)
        meta = st.page
        total_pages = meta.total_pages if meta else (1 if items else 0)
        truncated = total_pages > s.reporting_max_pages
        progress({'stage': 'fetching', 'pages_fetched': 1, 'total_pages': total_pages,
                  'total_elements': None if meta is None else meta.total_elements})
        for page in range(1, min(total_pages, s.reporting_max_pages)):
            p = await self.status(st.id, request.report_type, page)
            if p.status != 'COMPLETED' or (meta and p.page and (p.page.total_elements, p.page.total_pages)
                                           != (meta.total_elements, meta.total_pages)):
                raise VeracodeError('inconsistent_pagination')
            items.extend(p.items)
            progress({'pages_fetched': page + 1})
        expected = None if meta is None else meta.total_elements
        complete = not truncated and (expected is None or expected == len(items))
        reasons = []
        if truncated:
            reasons.append({'code': 'report_too_large', 'message': VeracodeError('report_too_large').message})
        elif not complete:
            reasons.append({'code': 'inconsistent_pagination',
                            'message': 'Itens lidos diferem de page_metadata.total_elements'})
        return items, {'complete': complete, 'truncated': truncated, 'reasons': reasons,
                       'items_processed': len(items), 'total_elements_reported': expected,
                       'pages_fetched': min(total_pages, s.reporting_max_pages), 'total_pages': total_pages,
                       'data_refresh_date': st.dates.get('data_refresh_date')}


# ---------------------------------------------------------------- execuções (memória do processo)

class JobStatus(StrEnum):
    PENDING = 'pending'
    PROCESSING = 'processing'
    FETCHING = 'fetching'
    DONE = 'done'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    id: str
    owner: dict
    request: ReportRequest
    mode: str
    status: JobStatus = JobStatus.PENDING
    created_at: str = field(default_factory=_now)
    finished_at: str | None = None
    veracode: dict = field(default_factory=dict)
    progress: dict = field(default_factory=lambda: {'stage': 'pending', 'polls': 0, 'pages_fetched': 0})
    usage: dict = field(default_factory=dict)
    result: dict | None = None
    error: dict | None = None
    task: asyncio.Task | None = None

    @property
    def finished(self) -> bool:
        return self.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED)

    def public(self) -> dict:
        out = {'job_id': self.id, 'status': self.status.value, 'owner': self.owner,
               'report_type': self.request.report_type, 'request': self.request.public(), 'mode': self.mode,
               'created_at': self.created_at, 'finished_at': self.finished_at, 'veracode': dict(self.veracode),
               'progress': dict(self.progress), 'usage': dict(self.usage), 'result': self.result,
               'error': self.error}
        if self.status == JobStatus.CANCELLED and self.veracode.get('report_id'):
            out['remote_note'] = ('A Reporting API não oferece cancelamento: o relatório gerado pode continuar na '
                                  'Veracode até expirar (report_expiration_date); nada foi lido depois do cancelamento')
        return out


class ReportingJobs:
    def __init__(self, settings: VeracodeSettings, pool: VeracodeHttpPool, *, sleep=asyncio.sleep,
                 clock: Callable[[], float] = time.monotonic, max_jobs: int = 50):
        self.settings, self.pool, self._sleep, self._clock = settings, pool, sleep, clock
        self.max_jobs = max_jobs
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._starts: deque[float] = deque()

    def active(self) -> int:
        return sum(not j.finished for j in self._jobs.values())

    def quota_left(self) -> int:
        now = self._clock()
        while self._starts and now - self._starts[0] >= 3600:
            self._starts.popleft()
        return self.settings.reporting_max_per_hour - len(self._starts)

    def start(self, owner: dict, request: ReportRequest, creds: Credentials, region: str) -> Job:
        if not self.settings.reporting_enabled:
            raise VeracodeError('reporting_disabled')
        job = Job(str(uuid.uuid4()), owner, request, self.settings.mode)
        self._starts.append(self._clock())
        self._jobs[job.id] = job
        while len(self._jobs) > self.max_jobs:
            victim = next((k for k, j in self._jobs.items() if j.finished), None)
            if victim is None:
                break
            self._jobs.pop(victim)
        job.task = asyncio.get_running_loop().create_task(self._execute(job, creds, region))
        logger.info('reporting job=%s tipo=%s iniciado', job.id, request.report_type)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        return list(reversed(self._jobs.values()))

    def cancel(self, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        if job is not None and not job.finished and job.task is not None:
            job.task.cancel()
        return job

    async def aclose(self) -> None:
        tasks = [j.task for j in self._jobs.values() if j.task and not j.task.done()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute(self, job: Job, creds: Credentials, region: str) -> None:
        client = ReportingClient(self.pool, creds, region, sleep=self._sleep, clock=self._clock)

        def progress(update: dict) -> None:
            stage = update.pop('stage', None)
            if stage:
                job.status = JobStatus(stage)
                job.progress['stage'] = stage
            for k in ('report_id', 'veracode_status', 'envelope', *_META_DATES):
                if k in update:
                    job.veracode[k] = update.pop(k)
            job.progress.update(update)

        try:
            job.status = JobStatus.PROCESSING
            job.result = await client.execute(job.request, progress)
            job.status = JobStatus.DONE
        except asyncio.CancelledError:
            job.status = JobStatus.CANCELLED
            job.error = {'code': 'cancelled', 'message': 'Execução cancelada localmente'}
        except VeracodeError as exc:
            job.status = JobStatus.FAILED
            job.error = exc.as_dict()
            if exc.code == 'forbidden':
                job.error['hint'] = ('HTTP 403: a Reporting API exige habilitação pela Veracode e o papel '
                                     '"Reporting API" na conta de API')
        except Exception as exc:  # noqa: BLE001 - só o tipo; nunca mensagens com dados
            logger.error('reporting job=%s falhou: %s', job.id, type(exc).__name__)
            job.status = JobStatus.FAILED
            job.error = {'code': 'internal_error', 'message': 'Falha interna no relatório'}
        finally:
            job.usage = {'requests': client.run.requests, 'retries': client.run.retries}
            job.finished_at = _now()
            job.progress['stage'] = job.status.value
            logger.info('reporting job=%s status=%s requisições=%s', job.id, job.status.value, client.run.requests)
