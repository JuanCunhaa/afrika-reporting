from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1]
REQUIRED=['CLAUDE.md','docs/PRODUCT.md','docs/STATUS.md','prompts/F00_START.md','prompts/F01_CLIENTS.md',
          'backend/app/main.py','backend/alembic.ini','backend/migrations/env.py','frontend/package.json']
for name in REQUIRED:
    if not (root/name).exists():
        sys.exit(f'ERRO: arquivo ausente: {name}')
if not list((root/'backend/migrations/versions').glob('*.py')):
    sys.exit('ERRO: nenhuma migration em backend/migrations/versions')
print('Estrutura F01: OK')
