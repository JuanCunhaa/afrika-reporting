"""Fila de exportação (F07): jobs em memória executados por UMA thread (um navegador por vez), com limites.

- Pedido aceito só depois das pré-checagens (revisão persistida, fonte aprovada, integridade): o job recebe a
  visualização já validada (dados imutáveis: revisão da apresentação + aprovações fixadas).
- Limites: fila (`MAX_QUEUE` aguardando => 429), prazo de renderização, tamanho do arquivo, retenção (`TTL_S`) e nº de
  jobs guardados. Arquivos em diretório temporário PRÓPRIO desta instância (`AFRIKA_EXPORT_DIR` absoluto ou o temp do
  sistema), um subdiretório por job, apagados na expiração e no desligamento. O cliente nunca informa caminho: baixa
  pelo id aleatório do job.
- Concluído com sucesso => evento de auditoria `presentation.exported` (ids, formato, SHA-256 e tamanho; nenhum dado).
"""
from __future__ import annotations

import logging
import os
import queue
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlalchemy.exc import IntegrityError, OperationalError

from app.export.errors import ExportError
from app.export.service import ExportResult, build_export

logger = logging.getLogger('afrika.export')
EXPORT_DIR_ENV = 'AFRIKA_EXPORT_DIR'
MAX_QUEUE = 4
MAX_JOBS = 50
TTL_S = 30 * 60


@dataclass
class Job:
    id: str
    presentation_id: str
    revision: int
    format: str
    operator: str
    owner_key: str
    status: str = 'queued'  # queued | running | done | failed
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    error: dict | None = None
    warnings: list[dict] = field(default_factory=list)
    report: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    filename: str | None = None
    media_type: str | None = None
    size: int | None = None
    sha256: str | None = None
    template: str = ''
    theme: str = ''
    path: Path | None = None  # privado (nunca exposto)

    def public(self) -> dict:
        out = {k: v for k, v in asdict(self).items() if k not in ('path', 'owner_key')}
        out['download_url'] = f'/api/exports/{self.id}/file' if self.status == 'done' else None
        return out


class ExportJobs:
    def __init__(self, session_factory, *, base_dir: Path | None = None,
                 runner: Callable[[dict, str], ExportResult] | None = None, timeout: float = 120.0,
                 max_queue: int = MAX_QUEUE, ttl: float = TTL_S, max_jobs: int = MAX_JOBS):
        configured = os.getenv(EXPORT_DIR_ENV)
        root = base_dir or (Path(configured) if configured and Path(configured).is_absolute()
                            else Path(tempfile.gettempdir()) / 'afrika-exports')
        root.mkdir(parents=True, exist_ok=True)
        self.base = Path(tempfile.mkdtemp(prefix='run-', dir=root))  # 0o700 em POSIX; temp do usuário no Windows
        self.session_factory = session_factory
        self.runner = runner or (lambda v, fmt: build_export(v, fmt, timeout=timeout))
        self.max_queue, self.ttl, self.max_jobs = max_queue, ttl, max_jobs
        self.lock = threading.Lock()
        self.jobs: dict[str, Job] = {}
        self.views: dict[str, dict] = {}
        self.q: queue.Queue[str | None] = queue.Queue()
        self.worker = threading.Thread(target=self._loop, name='afrika-export', daemon=True)
        self.worker.start()

    # ------------------------------------------------------------ API
    def submit(self, view: dict, fmt: str, operator: str) -> Job:
        self._gc()
        with self.lock:
            waiting = sum(1 for j in self.jobs.values() if j.status == 'queued')
            if waiting >= self.max_queue:
                raise ExportError('export_queue_full', 'Fila de exportação cheia: aguarde as exportações em andamento',
                                  status=429)
            job = Job(id=str(uuid.uuid4()), presentation_id=view['presentation']['id'],
                      revision=int(view['revision']['number']), format=fmt, operator=operator,
                      owner_key=view['owner']['key'],
                      template=f'{view["template"]["key"]}@{view["template"]["version"]}',
                      theme=f'{view["theme"]["id"]}@{view["theme"]["version"]}')
            self.jobs[job.id] = job
            self.views[job.id] = view
        self.q.put(job.id)
        return job

    def get(self, job_id: str) -> Job:
        self._gc()
        with self.lock:
            job = self.jobs.get(job_id)
        if job is None:
            raise ExportError('export_not_found', 'Exportação não encontrada (expirada ou inexistente)', status=404)
        return job

    def list_for(self, presentation_id: str) -> list[Job]:
        self._gc()
        with self.lock:
            return sorted((j for j in self.jobs.values() if j.presentation_id == presentation_id),
                          key=lambda j: j.created_at, reverse=True)

    def file(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status != 'done' or job.path is None or not job.path.is_file():
            raise ExportError('export_not_ready', 'Arquivo indisponível: a exportação não terminou com sucesso',
                              status=409)
        return job

    def close(self) -> None:
        self.q.put(None)
        self.worker.join(timeout=30)
        shutil.rmtree(self.base, ignore_errors=True)

    # ------------------------------------------------------------ execução
    def _loop(self) -> None:
        while True:
            job_id = self.q.get()
            if job_id is None:
                return
            with self.lock:
                job = self.jobs.get(job_id)
                v = self.views.pop(job_id, None)
            if job is None or v is None:
                continue
            job.status, job.started_at = 'running', time.time()
            try:
                res = self.runner(v, job.format)
                target = Path(tempfile.mkdtemp(prefix='job-', dir=self.base)) / res.filename
                target.write_bytes(res.data)
                job.path, job.filename, job.media_type = target, res.filename, res.media_type
                job.size, job.sha256 = len(res.data), res.sha256
                job.report, job.warnings, job.timings = res.report, list(res.warnings), res.timings
                self._audit(job)
                job.status = 'done'
            except ExportError as exc:
                job.status, job.error = 'failed', exc.public()
            except Exception:  # noqa: BLE001 — falha inesperada: registrada sem dados, job marcado como falho
                logger.exception('exportação %s falhou', job.id)
                job.status = 'failed'
                job.error = {'code': 'export_failed', 'message': 'Falha inesperada na exportação (veja o log local)',
                             'details': []}
            finally:
                job.finished_at = time.time()

    def _audit(self, job: Job) -> None:
        from app.orm import Presentation
        from app.presentations import service as presentations
        from app.snapshots import audit
        for attempt in range(3):
            with self.session_factory() as s:
                try:
                    p = s.get(Presentation, uuid.UUID(job.presentation_id))
                    r = presentations.get_revision(s, p, job.revision)
                    audit.append(s, 'presentation.exported', owner_key=p.owner_key, competence_id=p.competence_id,
                                 revision_id=r.primary_revision_id, actor=job.operator,
                                 details={'presentation_id': job.presentation_id, 'presentation_revision': job.revision,
                                          'format': job.format, 'sha256': job.sha256, 'size_bytes': job.size,
                                          'template': job.template, 'theme': job.theme})
                    s.commit()
                    return
                except (IntegrityError, OperationalError):
                    s.rollback()
                    time.sleep(0.2 * (attempt + 1))
        job.warnings.append({'code': 'audit_not_recorded', 'message': 'Arquivo gerado, mas o evento de auditoria não '
                                                                      'foi gravado (banco ocupado)'})

    def _gc(self) -> None:
        now = time.time()
        with self.lock:
            finished = sorted((j for j in self.jobs.values() if j.status in ('done', 'failed')),
                              key=lambda j: j.finished_at or 0)
            expired = [j for j in finished if now - (j.finished_at or now) > self.ttl]
            expired += [j for j in finished[:max(0, len(self.jobs) - self.max_jobs)] if j not in expired]
            for j in expired:
                self.jobs.pop(j.id, None)
                if j.path is not None:
                    shutil.rmtree(j.path.parent, ignore_errors=True)
