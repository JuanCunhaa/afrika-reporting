import os
from collections.abc import Mapping
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import (
    api, api_exports, api_interpretations, api_metrics, api_presentations, api_reconciliation, api_reporting, api_scopes,
    api_snapshots, api_veracode, backup, errors,
)
from app.local_only import LocalOnlyMiddleware
from app.db import assert_schema_ready, database_url, make_engine, session_factory
from app.env_loader import load_project_env
from app.export.jobs import ExportJobs
from app.interpretation.settings import InterpretationSettings
from app.metrics.runs import RunManager
from app.veracode.cache import DiscoveryCache
from app.veracode.discovery import DiscoveryService
from app.veracode.fixtures import FixtureVeracode
from app.veracode.reporting import ReportingJobs
from app.veracode.http import VeracodeHttpPool
from app.veracode.settings import VeracodeSettings

DESCRIPTION = ('F06B.1: cadastro de clientes/subclientes/conexões + descoberta Veracode SOMENTE LEITURA '
               '(aplicações, BUs, Teams, usuários, sandboxes e relacionamentos) + escopos versionados por domínio '
               '+ motor de indicadores (aplicações, SAST, SCA) com contratos, status e proveniência '
               '+ snapshots por competência, revisões, aprovação auditável e séries históricas '
               '+ Reporting API (única escrita autorizada: POST de geração de relatório, desligado por padrão) '
               '+ apresentações com templates e temas visuais versionados (ativos locais, fora do Git) '
               '+ exportação PPTX editável e PDF a partir da revisão persistida (F07; renderização local, sem rede) '
               '+ interpretação dos indicadores com validação determinística e revisão humana (F08; provedor local '
               'por padrão, nada enviado a terceiros). '
               'SEM AUTENTICAÇÃO — API apenas para uso local (127.0.0.1); não expor publicamente.')


def create_app(db_url: str | None = None, *, veracode_settings: VeracodeSettings | None = None,
               veracode_transport: httpx.AsyncBaseTransport | None = None,
               environ: Mapping[str, str] | None = None, sleep=None) -> FastAPI:
    """`veracode_transport`, `environ` e `sleep` existem para testes (transporte simulado, ambiente e relógio)."""
    url = db_url or database_url()
    engine = make_engine(url)
    settings = veracode_settings or VeracodeSettings.from_env()
    if veracode_transport is None and settings.mode == 'fixture':
        veracode_transport = FixtureVeracode().transport()  # tenant SINTÉTICO em processo; nunca a API real

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        assert_schema_ready(engine)  # falha cedo; nunca cria nem migra o banco automaticamente
        # Pool/semáforo criados dentro do event loop do servidor; fechados no desligamento.
        pool = VeracodeHttpPool(settings, veracode_transport)
        extra = {'sleep': sleep} if sleep is not None else {}
        app.state.veracode = DiscoveryService(settings, pool, DiscoveryCache(settings.cache_ttl,
                                                                            settings.cache_max_entries),
                                              environ=environ, **extra)
        app.state.metric_runs = RunManager(app.state.veracode)
        app.state.reporting = ReportingJobs(settings, pool, **extra)
        app.state.exports = ExportJobs(app.state.session_factory)  # F07: fila local de exportação PPTX/PDF
        try:
            yield
        finally:
            app.state.exports.close()
            await app.state.reporting.aclose()
            await app.state.metric_runs.aclose()
            await pool.aclose()
            engine.dispose()

    app = FastAPI(title='Afrika Reporting API', version='0.6.1', description=DESCRIPTION, lifespan=lifespan)
    app.state.engine = engine
    app.state.db_url = url
    app.state.backup_dir = backup.default_dir(url, environ)  # F11: backup automático antes de aprovar
    app.state.session_factory = session_factory(engine)
    app.state.interpretation = InterpretationSettings.from_env(environ)  # F08: padrão local, externo desligado

    origins = [s.strip() for s in os.getenv('CORS_ORIGINS', 'http://localhost:5173').split(',') if s.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'],
                       allow_headers=['Content-Type'])
    app.add_middleware(LocalOnlyMiddleware)  # mais externo: recusa origem/Host não-loopback antes de tudo
    errors.install(app)
    app.include_router(api.router)
    api_veracode.install(app)
    app.include_router(api_scopes.router)
    app.include_router(api_metrics.router)
    app.include_router(api_snapshots.router)
    app.include_router(api_reporting.router)
    app.include_router(api_presentations.router)
    app.include_router(api_exports.router)
    app.include_router(api_interpretations.router)
    app.include_router(api_reconciliation.router)

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'phase': 'F06B.1', 'data': 'local', 'auth': 'none', 'veracode_mode': settings.mode}

    return app


load_project_env()  # `.env` da raiz; nunca sobrescreve o ambiente do sistema
app = create_app()
