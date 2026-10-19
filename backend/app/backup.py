"""Backup e restauração LOCAIS do banco SQLite (F10, piloto local assistido).

- Backup: cópia consistente pela API de backup do SQLite (funciona com o backend aberto), seguida de verificação:
  `PRAGMA integrity_check`, revisão Alembic e SHA-256. O arquivo vai para `data/backups/` (ignorado pelo Git) ou um
  diretório fora do repositório; nunca para área versionada. Junto, um manifesto `.json` (sem dados de clientes).
- Restauração: só de arquivo íntegro, na MESMA revisão de esquema do código, com o backend PARADO e confirmação
  explícita. Antes de substituir, o banco atual é salvo como backup de segurança (nada se perde por engano).
- F11: toda aprovação de competência pela API faz antes um backup automático verificado (`before_approval`); se ele
  falhar, a aprovação é BLOQUEADA com o erro. O backup manual (`python -m app.cli backup-db`) continua disponível.
  Diretório: `AFRIKA_BACKUP_DIR` ou, por padrão, a pasta `backups/` ao lado do banco (`data/backups/` no banco padrão).
- Sem criptografia: o arquivo tem o mesmo conteúdo do banco (nomes de clientes, escopos, valores agregados; nunca
  credenciais nem findings). Proteja a pasta como o próprio banco.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app import db

BACKUP_DIR = db.REPO_ROOT / 'data' / 'backups'
BACKUP_DIR_ENV = 'AFRIKA_BACKUP_DIR'
ALLOWED_REPO_ROOTS = ('data', 'private')  # ignorados pelo .gitignore


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    sha256: str
    size_bytes: int
    alembic_revision: str | None
    integrity: str
    tables: dict[str, int]

    def public(self) -> dict:
        return {'file': str(self.path), 'sha256': self.sha256, 'size_bytes': self.size_bytes,
                'alembic_revision': self.alembic_revision, 'integrity': self.integrity, 'tables': self.tables}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def safe_dir(out: str | Path | None) -> Path:
    target = Path(out).resolve() if out else BACKUP_DIR.resolve()
    try:
        rel = target.relative_to(db.REPO_ROOT.resolve())
    except ValueError:
        return target  # fora do repositório
    if not rel.parts or rel.parts[0] not in ALLOWED_REPO_ROOTS:
        raise BackupError(f'Diretório de backup dentro do repositório e versionável: {rel}. Use um diretório fora do '
                          f'repositório ou sob data/ ou private/ (ignorados pelo Git).')
    return target


def default_dir(url: str, environ: Mapping[str, str] | None = None) -> Path:
    """`AFRIKA_BACKUP_DIR` ou `backups/` ao lado do arquivo do banco (no banco padrão: `data/backups/`)."""
    configured = (os.environ if environ is None else environ).get(BACKUP_DIR_ENV)
    if configured:
        return Path(configured)
    source = db.sqlite_file(url)
    return BACKUP_DIR if source is None else source.parent / 'backups'


def inspect(path: Path) -> BackupInfo:
    """Verifica um arquivo de banco SEM alterá-lo (abertura somente leitura)."""
    if not path.is_file():
        raise BackupError('Arquivo de backup não encontrado')
    try:
        conn = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)
    except sqlite3.Error:
        raise BackupError('Arquivo não é um banco SQLite legível') from None
    try:
        integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        revision = None
        if 'alembic_version' in names:
            row = conn.execute('SELECT version_num FROM alembic_version').fetchone()
            revision = row[0] if row else None
        tables = {n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names
                  if n != 'alembic_version' and not n.startswith('sqlite_')}
    except sqlite3.DatabaseError:
        raise BackupError('Arquivo não é um banco SQLite válido') from None
    finally:
        conn.close()
    return BackupInfo(path, _sha256(path), path.stat().st_size, revision, integrity, tables)


def _copy(source: Path, target: Path) -> None:
    src = sqlite3.connect(f'file:{source.as_posix()}?mode=ro', uri=True)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)  # cópia consistente mesmo com gravações concorrentes
        finally:
            dst.close()
    finally:
        src.close()


def backup(url: str | None = None, out: str | Path | None = None, *, now: datetime | None = None,
           label: str = 'backup') -> BackupInfo:
    url = url or db.database_url()
    source = db.sqlite_file(url)
    if source is None or not source.exists():
        raise BackupError('Backup suportado só para banco SQLite em arquivo existente')
    directory = safe_dir(out or default_dir(url))
    directory.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(timezone.utc)).strftime('%Y%m%dT%H%M%S%fZ')
    target = directory / f'afrika-reporting-{label}-{stamp}.sqlite3'
    if target.exists():
        raise BackupError('Já existe um backup com o mesmo nome; tente de novo')
    _copy(source, target)
    info = inspect(target)
    if info.integrity != 'ok':
        target.unlink(missing_ok=True)
        raise BackupError('Backup gerado falhou na verificação de integridade (removido)')
    manifest = {**info.public(), 'file': target.name, 'source': source.name,
                'created_at': (now or datetime.now(timezone.utc)).isoformat(), 'encrypted': False}
    target.with_suffix('.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return info


def before_approval(url: str, out: str | Path) -> BackupInfo:
    """Backup automático e verificado ANTES de aprovar (F11). Qualquer falha vira `BackupError` (bloqueia)."""
    try:
        return backup(url, out, label='antes-da-aprovacao')
    except BackupError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise BackupError(f'falha de E/S ou do SQLite ao copiar o banco ({type(exc).__name__})') from None


def restore(backup_file: str | Path, url: str | None = None, *, confirm: bool = False,
            safety_dir: str | Path | None = None) -> dict:
    """Substitui o banco atual pelo backup verificado. Exige `confirm` e o backend parado."""
    if not confirm:
        raise BackupError('Restauração exige confirmação explícita (--confirm) e o backend PARADO')
    url = url or db.database_url()
    target = db.sqlite_file(url)
    if target is None:
        raise BackupError('Restauração suportada só para banco SQLite em arquivo')
    info = inspect(Path(backup_file))
    if info.integrity != 'ok':
        raise BackupError('Backup íntegro? NÃO — PRAGMA integrity_check falhou; nada foi alterado')
    head = db.head_revision()
    if info.alembic_revision != head:
        raise BackupError(f'Backup na revisão de esquema {info.alembic_revision!r}, código espera {head!r}: restaure '
                          'com a versão do código correspondente; nada foi alterado')
    safety = None
    if target.exists():
        # padrão: ao lado do backup restaurado (mesma pasta protegida), nunca em área versionada
        safety = backup(url, safety_dir or info.path.parent, label='antes-da-restauracao')
    target.parent.mkdir(parents=True, exist_ok=True)
    _copy(info.path, target)
    restored = inspect(target)
    if restored.integrity != 'ok' or restored.tables != info.tables:
        raise BackupError('Verificação pós-restauração falhou; o backup de segurança foi preservado')
    return {'restored_from': str(info.path), 'sha256': info.sha256, 'alembic_revision': info.alembic_revision,
            'tables': restored.tables, 'safety_backup': None if safety is None else str(safety.path)}
