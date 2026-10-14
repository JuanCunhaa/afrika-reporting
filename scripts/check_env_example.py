"""Verifica se um arquivo .env de EXEMPLO contém só nomes de variáveis e placeholders.

NUNCA imprime valores: apenas nome da variável, classificação e tamanho do valor.
Uso (stdlib apenas):  python scripts/check_env_example.py [caminho]   (padrão: .env.example)
Saída 0 = seguro para versionar; 1 = revisar manualmente; 2 = arquivo ausente/ilegível.
Recusa-se a analisar `.env` real (só arquivos *.example / *.sample / *.template).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SECRET_KEY_NAME = re.compile(r'(KEY|SECRET|TOKEN|PASSWORD|PASSWD|PWD|HMAC|CREDENTIAL|API_ID|PRIVATE)', re.I)
PLACEHOLDER = re.compile(
    r'^(<[^<>]*>|\$\{[A-Z0-9_]+\}|changeme|change[-_]me|replace[-_]?me|your[-_].*|example.*|placeholder|'
    r'x{3,}|\*{3,}|todo|tbd|dummy|fake|none|null)$', re.I)
SAFE_VALUE = re.compile(
    r'^(true|false|yes|no|on|off|\d{1,6}|debug|info|warning|error|development|production|local|test|'
    r'https?://(localhost|127\.0\.0\.1)(:\d+)?(/\S*)?(,https?://(localhost|127\.0\.0\.1)(:\d+)?(/\S*)?)*|'
    r'sqlite:///[\w./-]*|env:[A-Z][A-Z0-9_]*|[\w.-]*\.sqlite3?)$', re.I)
SECRET_LIKE = re.compile(r'[0-9a-fA-F]{24,}|[A-Za-z0-9+/=_-]{40,}|-----BEGIN|AKIA[0-9A-Z]{16}|ghp_|xox[abp]-')


def classify(key: str, value: str) -> str:
    v = value.strip().strip('"').strip("'")
    if not v:
        return 'ok:vazio'
    if SECRET_LIKE.search(v):
        return 'REVISAR:valor-parece-segredo'
    if PLACEHOLDER.match(v):
        return 'ok:placeholder'
    if SECRET_KEY_NAME.search(key):
        return 'REVISAR:variavel-sensivel-com-valor'
    if SAFE_VALUE.match(v):
        return 'ok:valor-padrao-nao-secreto'
    return 'REVISAR:valor-nao-reconhecido'


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else '.env.example')
    if not re.search(r'\.(example|sample|template)$', path.name):
        print(f'Recusado: {path.name} não é arquivo de exemplo; este script não lê .env real.')
        return 2
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError as exc:
        print(f'{path}: não foi possível ler ({type(exc).__name__})')
        return 2

    problems = 0
    for n, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith('#'):
            if SECRET_LIKE.search(line):
                print(f'linha {n}: comentário  REVISAR:comentario-parece-segredo')
                problems += 1
            continue
        line = re.sub(r'^export\s+', '', line)
        if '=' not in line:
            print(f'linha {n}: REVISAR:linha-sem-atribuicao')
            problems += 1
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            print(f'linha {n}: REVISAR:nome-invalido')
            problems += 1
            continue
        verdict = classify(key, value)
        problems += verdict.startswith('REVISAR')
        print(f'linha {n}: {key:<32} {verdict:<36} tamanho={len(value.strip())}')
    print(f'Resultado: {"SEGURO para versionar" if not problems else f"{problems} item(ns) para revisão manual"}')
    return 0 if not problems else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
