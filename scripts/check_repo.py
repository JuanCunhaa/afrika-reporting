from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
REQUIRED=['CLAUDE.md','docs/PRODUCT.md','docs/STATUS.md','prompts/F00_START.md','prompts/F01_CLIENTS.md','prompts/F02_VERACODE.md','prompts/F03_SCOPES.md','prompts/F04_METRICS.md','docs/SCOPES.md','backend/app/scopes/rules.py',
          'docs/METRIC_CATALOG.md','docs/API_SOURCE_MATRIX.md','prompts/F04_1_SOURCES.md','backend/app/metrics/registry.py','backend/app/metrics/engine.py',
          'backend/app/veracode/http.py','docs/VERACODE_INTEGRATION.md',
          'docs/SNAPSHOTS.md','prompts/F05_SNAPSHOTS.md','backend/app/snapshots/service.py','backend/app/veracode/reporting_policy.py',
          'docs/PRESENTATIONS.md','docs/PRESENTATION_CONTRACTS.md','prompts/F06A_PRESENTATIONS.md',
          'backend/app/presentations/charts.py','backend/app/presentations/templates.py',
          'docs/THEMES.md','docs/PPTX_INSPECTION.md','docs/VISUAL_REGRESSION.md','prompts/F06B_1_VISUAL_ENGINE.md',
          'docs/AFRIKA_TEMPLATE.md','prompts/F06B_AFRIKA_TEMPLATE.md','frontend/visual/reference-map.json',
          'backend/app/presentations/themes.py','backend/app/presentations/assets.py','backend/app/presentations/pptx_inspect.py',
          'frontend/visual/diff.ts','frontend/visual/tolerances.json',
          'backend/app/main.py','backend/alembic.ini','backend/migrations/env.py','frontend/package.json']
for name in REQUIRED:
    if not (root/name).exists():
        sys.exit(f'ERRO: arquivo ausente: {name}')
if not list((root/'backend/migrations/versions').glob('*.py')):
    sys.exit('ERRO: nenhuma migration em backend/migrations/versions')
# F06B: nenhum arquivo de referência (PowerPoint/PDF) ou conteúdo de references/ pode estar rastreado
import subprocess
try:
    tracked = subprocess.run(['git', 'ls-files'], cwd=root, capture_output=True, text=True, check=True).stdout.splitlines()
except (OSError, subprocess.CalledProcessError):
    tracked = []
FORBIDDEN_EXT = ('.pptx', '.potx', '.pptm', '.ppt', '.ppsx', '.pdf', '.key')
bad = [t for t in tracked if t.lower().endswith(FORBIDDEN_EXT) or t.startswith('references/')]
if bad:
    sys.exit(f'ERRO: arquivos de referência rastreados pelo Git (proibido): {bad[:5]}')
# F06B: o cliente/unidade do PowerPoint de referência não pode ser citado em nada versionado (só SHA-256 aqui)
import hashlib, re
FORBIDDEN_SHA256 = {'50d1e8ab28a0dd129a37e232c47357e20e97bada6fed3737ffa4ddb18dd1f1c3',
                    'e5cb822160e3aca3301207f8169ff47835ba65e228977637412b525e7f21222d'}
hits = []
for t in tracked:
    if t.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.ico', '.woff', '.woff2', '.ttf', '.zip', '.svg')):
        continue
    try:
        words = re.findall(r'[a-z0-9]+', (root / t).read_text(encoding='utf-8', errors='ignore').lower())
    except OSError:
        continue
    grams = words + [f'{a} {b}' for a, b in zip(words, words[1:])]
    if any(hashlib.sha256(g.encode()).hexdigest() in FORBIDDEN_SHA256 for g in set(grams)):
        hits.append(t)
hits = [h for h in hits if h != 'backend/tests/test_afrika_template.py']  # usa um termo genérico para testar o filtro
if hits:
    sys.exit(f'ERRO: nome do cliente/unidade da referência em arquivo versionado: {hits[:5]}')
print('Estrutura F06B: OK')
