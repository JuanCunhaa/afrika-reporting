import os
from collections.abc import Mapping
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import api, api_veracode, errors
from app.local_only import LocalOnlyMiddleware
from app.db import assert_schema_ready, database_url, make_engine, session_factory
from app.models import MetricSnapshot
from app.veracode.cache import DiscoveryCache
from app.veracode.discovery import DiscoveryService
from app.veracode.fixtures import FixtureVeracode
from app.veracode.http import VeracodeHttpPool
from app.veracode.settings import VeracodeSettings

DESCRIPTION = ('F02: cadastro de clientes/subclientes/conexões + descoberta Veracode SOMENTE LEITURA '
               '(aplicações, BUs, Teams, usuários, sandboxes e relacionamentos). '
               'SEM AUTENTICAÇÃO — API apenas para uso local (127.0.0.1); não expor publicamente.')


def create_app(db_url: str | None = None, *, veracode_settings: VeracodeSettings | None = None,
               veracode_transport: httpx.AsyncBaseTransport | None = None,
               environ: Mapping[str, str] | None = None, sleep=None) -> FastAPI:
    """`veracode_transport`, `environ` e `sleep` existem para testes (transporte simulado, ambiente e relógio)."""
    engine = make_engine(db_url or database_url())
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
        try:
            yield
        finally:
            await pool.aclose()
            engine.dispose()

    app = FastAPI(title='Afrika Reporting API', version='0.2.0', description=DESCRIPTION, lifespan=lifespan)
    app.state.engine = engine
    app.state.session_factory = session_factory(engine)

    origins = [s.strip() for s in os.getenv('CORS_ORIGINS', 'http://localhost:5173').split(',') if s.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=['GET', 'POST', 'PATCH', 'DELETE'],
                       allow_headers=['Content-Type'])
    app.add_middleware(LocalOnlyMiddleware)  # mais externo: recusa origem/Host não-loopback antes de tudo
    errors.install(app)
    app.include_router(api.router)
    api_veracode.install(app)

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'phase': 'F02', 'data': 'local', 'auth': 'none', 'veracode_mode': settings.mode}

    @app.get('/api/demo/metrics', response_model=list[MetricSnapshot])
    def demo_metrics():
        return [MetricSnapshot(metric_id='sast.open.medium.policy', competence='2026-09', value=123,
                               source='SYNTHETIC', status='DEMO_ONLY')]

    return app


app = create_app()
