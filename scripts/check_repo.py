from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
REQUIRED=['CLAUDE.md','docs/PRODUCT.md','docs/STATUS.md','prompts/F00_START.md','prompts/F01_CLIENTS.md','prompts/F02_VERACODE.md','prompts/F03_SCOPES.md','prompts/F04_METRICS.md','docs/SCOPES.md','backend/app/scopes/rules.py',
          'docs/METRIC_CATALOG.md','docs/API_SOURCE_MATRIX.md','prompts/F04_1_SOURCES.md','backend/app/metrics/registry.py','backend/app/metrics/engine.py',
          'backend/app/veracode/http.py','docs/VERACODE_INTEGRATION.md',
          'backend/app/main.py','backend/alembic.ini','backend/migrations/env.py','frontend/package.json']
for name in REQUIRED:
    if not (root/name).exists():
        sys.exit(f'ERRO: arquivo ausente: {name}')
if not list((root/'backend/migrations/versions').glob('*.py')):
    sys.exit('ERRO: nenhuma migration em backend/migrations/versions')
print('Estrutura F04.1: OK')
