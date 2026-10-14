"""Carrega o `.env` da RAIZ do repositório, independente do diretório de onde o backend é iniciado.

- Precedência: variável já definida no ambiente do sistema (mesmo vazia) NUNCA é sobrescrita pelo `.env`.
- Sem interpolação (`${VAR}`): valores são usados literalmente.
- Devolve só os NOMES das variáveis adicionadas; valores nunca são logados nem devolvidos.
- `AFRIKA_DOTENV_DISABLED=1` desativa o carregamento (suíte unitária e E2E: credenciais reais nunca entram
  nesses processos).
"""
from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[2]
DOTENV_PATH = REPO_ROOT / '.env'
DISABLE_VAR = 'AFRIKA_DOTENV_DISABLED'


def dotenv_disabled(environ: MutableMapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get(DISABLE_VAR, '').strip().lower() in ('1', 'true', 'yes')


def load_project_env(path: Path | None = None, environ: MutableMapping[str, str] | None = None) -> list[str]:
    env = os.environ if environ is None else environ
    if dotenv_disabled(env):
        return []
    path = DOTENV_PATH if path is None else path
    if not path.is_file():
        return []
    added = []
    for key, value in dotenv_values(path, interpolate=False, encoding='utf-8').items():
        if value is None or key in env:
            continue
        env[key] = value
        added.append(key)
    return added
