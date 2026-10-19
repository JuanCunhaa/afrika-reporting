"""Migrations Alembic, integridade referencial no banco e recusa de iniciar sem esquema."""
import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app import db
from app.main import create_app
from app.orm import Base
from conftest import sqlite_url

F04_TABLES = {'connections', 'clients', 'subclients', 'scope_definitions', 'scope_versions', 'alembic_version'}
F05_TABLES = {'collection_runs', 'competences', 'competence_revisions', 'metric_snapshots', 'manual_changes',
              'approvals', 'audit_events'}
F06_TABLES = {'presentation_templates', 'owner_template_selections', 'presentations', 'presentation_revisions'}
F06B_TABLES = {'presentation_themes'}
F08_TABLES = {'interpretation_versions', 'interpretation_events', 'interpretation_slide_settings'}
F10_TABLES = {'metric_conferences'}
TABLES = F04_TABLES | F05_TABLES | F06_TABLES | F06B_TABLES | F08_TABLES | F10_TABLES
F01_TABLES = {'connections', 'clients', 'subclients', 'alembic_version'}


def test_upgrade_on_new_database_creates_schema_at_head(tmp_path):
    url = sqlite_url(tmp_path / 'novo.sqlite3')
    db.upgrade(url)
    engine = db.make_engine(url)
    try:
        assert set(inspect(engine).get_table_names()) == TABLES
        assert db.current_revision(engine) == db.head_revision() == '0008_metric_conferences'
    finally:
        engine.dispose()


def test_migrations_match_orm_models(db_url):
    """A migration é a fonte do esquema; o ORM não pode divergir dela (sem create_all)."""
    engine = db.make_engine(db_url)
    try:
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    finally:
        engine.dispose()
    assert diff == []


def test_downgrade_and_upgrade_roundtrip(db_url):
    db.downgrade(db_url, 'base')
    engine = db.make_engine(db_url)
    try:
        assert set(inspect(engine).get_table_names()) == {'alembic_version'}
        assert db.current_revision(engine) is None
        db.upgrade(db_url)
        assert set(inspect(engine).get_table_names()) == TABLES
    finally:
        engine.dispose()


def test_migrate_is_idempotent_and_preserves_data(db_url):
    with TestClient(create_app(db_url)) as api:
        cid = api.post('/api/clients', json={'name': 'Persistente'}).json()['id']
    db.upgrade(db_url)  # rodar de novo (atualização sem pendências) não apaga nada
    with TestClient(create_app(db_url)) as api:
        assert api.get(f'/api/clients/{cid}').json()['name'] == 'Persistente'


def test_app_refuses_to_start_without_migrations(tmp_path):
    missing = tmp_path / 'inexistente.sqlite3'
    with pytest.raises(db.SchemaNotReadyError, match='migrate'):
        with TestClient(create_app(sqlite_url(missing))):
            pass
    assert not missing.exists()  # não criou banco por conta própria

    outdated = tmp_path / 'vazio.sqlite3'
    db.upgrade(sqlite_url(outdated))
    db.downgrade(sqlite_url(outdated), 'base')
    with pytest.raises(db.SchemaNotReadyError, match='revisão'):
        with TestClient(create_app(sqlite_url(outdated))):
            pass


def test_foreign_keys_enforced_at_database_level(db_url):
    engine = db.make_engine(db_url)
    try:
        with engine.connect() as conn:
            assert conn.execute(text('PRAGMA foreign_keys')).scalar() == 1
        with engine.begin() as conn:
            now = '2026-01-01 00:00:00'
            client_id = uuid.uuid4().hex
            conn.execute(text("INSERT INTO clients (id, name, name_key, display_name, is_active, report_mode, "
                              "created_at, updated_at) VALUES (:id, 'C', 'c', 'C', 1, 'both', :now, :now)"),
                         {'id': client_id, 'now': now})
            conn.execute(text("INSERT INTO subclients (id, client_id, name, name_key, display_name, is_active, "
                              "created_at, updated_at) VALUES (:id, :cid, 'S', 's', 'S', 1, :now, :now)"),
                         {'id': uuid.uuid4().hex, 'cid': client_id, 'now': now})
        # subcliente órfão
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(text("INSERT INTO subclients (id, client_id, name, name_key, display_name, is_active, "
                              "created_at, updated_at) VALUES (:id, :cid, 'X', 'x', 'X', 1, :now, :now)"),
                         {'id': uuid.uuid4().hex, 'cid': uuid.uuid4().hex, 'now': now})
        # exclusão de cliente com subclientes (RESTRICT)
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(text('DELETE FROM clients WHERE id = :id'), {'id': client_id})
        # conexão inexistente
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(text('UPDATE clients SET connection_id = :c WHERE id = :id'),
                         {'c': uuid.uuid4().hex, 'id': client_id})
        # modo de relatório fora do domínio (CHECK)
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(text("UPDATE clients SET report_mode = 'x' WHERE id = :id"), {'id': client_id})
    finally:
        engine.dispose()


def test_integrity_error_message_hides_parameters(db_url):
    engine = db.make_engine(db_url)
    try:
        with pytest.raises(IntegrityError) as info, engine.begin() as conn:
            conn.execute(text("INSERT INTO connections (id, name, name_key, region, credential_ref, created_at, "
                              "updated_at) VALUES (:id, 'n', 'n', 'mars', :ref, '2026-01-01', '2026-01-01')"),
                         {'id': uuid.uuid4().hex, 'ref': 'env:SENTINELA_PARAMETRO'})
        assert 'SENTINELA_PARAMETRO' not in str(info.value)
    finally:
        engine.dispose()


# ---------------------------------------------------------------- F03: escopos

def test_f03_downgrade_to_f01_keeps_registry_and_upgrade_restores(db_url):
    with TestClient(create_app(db_url)) as api:
        cid = api.post('/api/clients', json={'name': 'Mantido no downgrade'}).json()['id']
    db.downgrade(db_url, '0001_registry')
    engine = db.make_engine(db_url)
    try:
        assert set(inspect(engine).get_table_names()) == F01_TABLES
        with engine.connect() as conn:
            assert conn.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'")).all() == []
        db.upgrade(db_url)
        assert set(inspect(engine).get_table_names()) == TABLES
    finally:
        engine.dispose()
    with TestClient(create_app(db_url)) as api:
        assert api.get(f'/api/clients/{cid}').status_code == 200


def _insert_scope(conn, client_id: str) -> str:
    def_id = uuid.uuid4().hex
    now = '2026-01-01 00:00:00'
    conn.execute(text("INSERT INTO scope_definitions (id, client_id, subclient_id, owner_key, domain, status, "
                      "created_at, updated_at) VALUES (:id, :cid, NULL, :ok, 'applications', 'active', :now, :now)"),
                 {'id': def_id, 'cid': client_id, 'ok': f'client:{client_id}', 'now': now})
    conn.execute(text("INSERT INTO scope_versions (id, definition_id, version, status, rule_json, options_json, "
                      "rule_hash, connection_mode, coverage_ack, note, created_at) VALUES (:id, :d, 1, 'active', "
                      "'{\"op\":\"all\"}', '{}', 'h', 'client', 0, NULL, :now)"),
                 {'id': uuid.uuid4().hex, 'd': def_id, 'now': now})
    return def_id


def test_scope_versions_are_immutable_at_database_level(db_url):
    engine = db.make_engine(db_url)
    try:
        client_id = uuid.uuid4().hex
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO clients (id, name, name_key, display_name, is_active, report_mode, "
                              "created_at, updated_at) VALUES (:id, 'C', 'c', 'C', 1, 'both', :n, :n)"),
                         {'id': client_id, 'n': '2026-01-01 00:00:00'})
            def_id = _insert_scope(conn, client_id)
        for stmt in ("UPDATE scope_versions SET rule_json = '{}'", "UPDATE scope_versions SET version = 9",
                     "UPDATE scope_versions SET note = 'x'", 'DELETE FROM scope_versions'):
            with pytest.raises(IntegrityError, match='scope_version'), engine.begin() as conn:
                conn.execute(text(stmt))
        # segunda versão ativa na mesma definição: índice único parcial
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(text("INSERT INTO scope_versions (id, definition_id, version, status, rule_json, "
                              "options_json, rule_hash, connection_mode, coverage_ack, created_at) VALUES (:id, :d, 2, "
                              "'active', '{}', '{}', 'h', 'client', 0, '2026-01-01')"),
                         {'id': uuid.uuid4().hex, 'd': def_id})
        # active -> superseded permitido; superseded -> active proibido
        with engine.begin() as conn:
            conn.execute(text("UPDATE scope_versions SET status = 'superseded'"))
        with pytest.raises(IntegrityError, match='scope_version_status_transition'), engine.begin() as conn:
            conn.execute(text("UPDATE scope_versions SET status = 'active'"))
        # dono com escopo não pode ser excluído (RESTRICT) e domínio fora da lista é recusado (CHECK)
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(text('UPDATE clients SET is_active = 0'))
            conn.execute(text('DELETE FROM clients WHERE id = :id'), {'id': client_id})
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(text("UPDATE scope_definitions SET domain = 'findings'"))
    finally:
        engine.dispose()



# ---------------------------------------------------------------- F05: snapshots

def test_f05_upgrade_on_existing_f04_database_preserves_data(tmp_path):
    """Banco em uso na F04.1 (revisão 0003, com cliente, subcliente e escopo) recebe a 0004 sem perder nada."""
    url = sqlite_url(tmp_path / 'f04.sqlite3')
    db.upgrade(url, '0003_client_timezone')
    engine = db.make_engine(url)
    client_id = uuid.uuid4()
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO clients (id, name, name_key, display_name, is_active, report_mode, timezone, "
                              "created_at, updated_at) VALUES (:id, 'Legado', 'legado', 'Legado', 1, 'both', "
                              "'America/Sao_Paulo', :n, :n)"), {'id': client_id.hex, 'n': '2026-01-01 00:00:00'})
            _insert_scope(conn, client_id.hex)
        db.upgrade(url)
        assert db.current_revision(engine) == '0008_metric_conferences'
        assert set(inspect(engine).get_table_names()) == TABLES
        with engine.connect() as conn:
            views = conn.execute(text("SELECT name FROM sqlite_master WHERE type='view'")).scalars().all()
        assert views == ['v_official_revisions']
        with engine.connect() as conn:
            assert conn.execute(text('SELECT COUNT(*) FROM scope_versions')).scalar() == 1
    finally:
        engine.dispose()
    with TestClient(create_app(url)) as api:
        assert api.get(f'/api/clients/{client_id}').json()['timezone'] == 'America/Sao_Paulo'
        r = api.post('/api/competences', json={'owner_kind': 'client', 'owner_id': str(client_id),
                                               'competence': '2026-09', 'operator': 'Operador Sintético'})
        assert r.status_code == 201 and r.json()['timezone'] == 'America/Sao_Paulo'


def test_f05_downgrade_refuses_to_drop_approved_history(db_url, monkeypatch):
    with TestClient(create_app(db_url)) as api:
        cid = api.post('/api/clients', json={'name': 'Com histórico'}).json()['id']
        comp = api.post('/api/competences', json={'owner_kind': 'client', 'owner_id': cid, 'competence': '2026-09',
                                                  'operator': 'Operador'}).json()['id']
        base = f'/api/competences/{comp}/revisions/1'
        api.put(f'{base}/required', json={'metric_ids': ['licenses.usage'], 'operator': 'Op', 'expected_lock_version': 1})
        api.put(f'{base}/metrics/licenses.usage', json={'value': 1, 'justification': 'Valor sintético de teste',
                                                         'operator': 'Op', 'expected_lock_version': 2})
        api.post(f'{base}/submit', json={'operator': 'Op', 'expected_lock_version': 3})
        assert api.post(f'{base}/approve', json={'approver': 'Aprovador', 'expected_lock_version': 4}).status_code == 200
    monkeypatch.delenv('AFRIKA_ALLOW_DESTRUCTIVE_DOWNGRADE', raising=False)
    with pytest.raises(RuntimeError, match='downgrade recusado'):
        db.downgrade(db_url, '0003_client_timezone')
    engine = db.make_engine(db_url)
    try:
        assert db.current_revision(engine) == '0004_snapshots'  # 0006 e 0005 (vazias) desceram; a 0004 recusou
        with engine.connect() as conn:
            assert conn.execute(text('SELECT COUNT(*) FROM approvals')).scalar() == 1
    finally:
        engine.dispose()
