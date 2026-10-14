import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import api, errors
from app.db import assert_schema_ready, database_url, make_engine, session_factory
from app.models import MetricSnapshot

DESCRIPTION = ('F01: cadastro persistente de clientes, subclientes e conexões (somente metadados). '
               'Sem integração Veracode. SEM AUTENTICAÇÃO — API apenas para uso local; não expor publicamente.')


def create_app(db_url: str | None = None) -> FastAPI:
    engine = make_engine(db_url or database_url())

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        assert_schema_ready(engine)  # falha cedo; nunca cria nem migra o banco automaticamente
        yield
        engine.dispose()

    app = FastAPI(title='Afrika Reporting API', version='0.1.0', description=DESCRIPTION, lifespan=lifespan)
    app.state.engine = engine
    app.state.session_factory = session_factory(engine)

    origins = [s.strip() for s in os.getenv('CORS_ORIGINS', 'http://localhost:5173').split(',') if s.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=['GET', 'POST', 'PATCH', 'DELETE'],
                       allow_headers=['Content-Type'])
    errors.install(app)
    app.include_router(api.router)

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'phase': 'F01', 'data': 'local', 'auth': 'none'}

    @app.get('/api/demo/metrics', response_model=list[MetricSnapshot])
    def demo_metrics():
        return [MetricSnapshot(metric_id='sast.open.medium.policy', competence='2026-09', value=123,
                               source='SYNTHETIC', status='DEMO_ONLY')]

    return app


app = create_app()
