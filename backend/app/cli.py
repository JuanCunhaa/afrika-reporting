"""Comandos locais. Execute a partir de `backend/`:

    python -m app.cli migrate      # cria/atualiza o esquema via Alembic (não apaga dados)
    python -m app.cli db-status    # mostra caminho do banco e revisão atual x esperada
    python -m app.cli seed-demo    # insere dados SINTÉTICOS da demo (idempotente)

F06B.1 (preparação do motor visual; nada é enviado para fora da máquina):

    python -m app.cli inspect-pptx ARQUIVO.pptx [--out DIR] [--privacy strict|structural] [--theme-draft]
    python -m app.cli synthetic-pptx SAIDA.pptx           # PPTX sintético para testar a inspeção
    python -m app.cli theme-asset-add ARQUIVO              # logo/fonte para o armazenamento LOCAL de ativos
    python -m app.cli theme-create --key K --file TEMA.json --operator NOME [--expected-version N]

F07 (exportação local; mesmas regras da API — revisão persistida, fonte aprovada, integridade, overflow):

    python -m app.cli export --presentation UUID --revision N --format pptx|pdf [--out DIR]

F10 (piloto local; arquivos nunca em área versionada):

    python -m app.cli backup-db [--out DIR]                 # cópia consistente + integrity_check + SHA-256
    python -m app.cli restore-db ARQUIVO.sqlite3 --confirm  # backend PARADO; salva o banco atual antes

Banco: AFRIKA_DATABASE_URL ou data/afrika-reporting.sqlite3 na raiz do repo.
Relatórios de inspeção: output/pptx-inspection/<sha256[:12]>/ (ignorado pelo Git) ou --out fora do repositório.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

from app import db
from app.env_loader import load_project_env
from app.seed import seed_demo

IGNORED_OUTPUT_ROOTS = ('output', 'private', 'data')  # ignorados pelo .gitignore


def _display_url(url: str) -> str:
    path = db.sqlite_file(url)
    return str(path) if path is not None else make_url(url).render_as_string(hide_password=True)


def safe_output_dir(out: str | None, sha256: str) -> Path:
    """Relatórios nunca caem em área versionada: fora do repositório ou sob output/, private/ ou data/."""
    target = Path(out).resolve() if out else (db.REPO_ROOT / 'output' / 'pptx-inspection' / sha256[:12])
    try:
        rel = target.resolve().relative_to(db.REPO_ROOT.resolve())
    except ValueError:
        return target  # fora do repositório
    if not rel.parts or rel.parts[0] not in IGNORED_OUTPUT_ROOTS:
        raise SystemExit(f'Diretório de saída dentro do repositório e versionável: {rel}. Use um diretório fora do '
                         f'repositório ou sob {", ".join(r + "/" for r in IGNORED_OUTPUT_ROOTS)} (ignorados pelo Git).')
    return target


def _inspect(args) -> int:
    from app.presentations import pptx_inspect
    try:
        report = pptx_inspect.inspect(args.file, privacy=args.privacy)
    except (pptx_inspect.PptxError, FileNotFoundError) as exc:
        print(f'Arquivo recusado: {exc}', file=sys.stderr)
        return 1
    out = safe_output_dir(args.out, report['source']['sha256'])
    out.mkdir(parents=True, exist_ok=True)
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (out / 'report.md').write_text(pptx_inspect.render_markdown(report), encoding='utf-8')
    if args.wireframes:
        (out / 'wireframes.html').write_text(pptx_inspect.wireframes_html(report), encoding='utf-8')
    if args.theme_draft:
        draft = pptx_inspect.theme_draft(report)
        (out / 'theme-draft.json').write_text(json.dumps(draft, ensure_ascii=False, indent=2) + '\n',
                                              encoding='utf-8')
    p = report['presentation']
    print(f'Inspeção local concluída ({report["privacy"]}): {p["slides"]} slides, {p["masters"]} master(s), '
          f'{p["layouts"]} layout(s), {p["size"]["px_96dpi"][0]:g}×{p["size"]["px_96dpi"][1]:g} px '
          f'({p["size"]["aspect_ratio"]}); {len(report["not_directly_reproducible"])} tipo(s) de elemento não '
          'reproduzível diretamente.')
    print(f'Relatório: {out}')
    return 0


def _theme_create(session, args) -> int:
    from app.errors import ApiError
    from app.presentations import themes
    raw = json.loads(Path(args.file).read_text(encoding='utf-8'))
    try:
        t = (themes.create_version(session, args.key, raw, args.operator, args.expected_version)
             if args.expected_version else themes.create(session, args.key, raw, args.operator))
    except ApiError as exc:
        details = '; '.join(f"{d['field']}: {d['message']}" for d in exc.details or [])
        print(f'{exc.message}: {details}', file=sys.stderr)
        return 1
    print(f'Tema {t["id"]}@{t["version"]} criado (hash {t["definition_hash"][:16]}…)')
    return 0


def _export(session, args) -> int:
    import uuid
    from app.errors import ApiError
    from app.export import service as export_service
    from app.export.errors import ExportError
    from app.presentations import service
    out = safe_output_dir(args.out or str(db.REPO_ROOT / 'output' / 'exports'), '')
    try:
        p = service.get(session, uuid.UUID(args.presentation))
        v = export_service.precheck(session, p, service.get_revision(session, p, args.revision))
        res = export_service.build_export(v, args.format)
    except (ApiError, ExportError, ValueError) as exc:
        details = '; '.join(f"{d.get('field', '')}: {d['message']}" for d in getattr(exc, 'details', None) or [])
        print(f'Exportação recusada: {getattr(exc, "message", str(exc))}{": " + details if details else ""}',
              file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    target = out / res.filename
    target.write_bytes(res.data)
    print(json.dumps({'file': str(target), 'sha256': res.sha256, 'size_bytes': len(res.data), 'timings': res.timings,
                      'warnings': res.warnings}, ensure_ascii=False, indent=2))
    return 0


def _db_command(args) -> int:
    url = db.database_url()
    print(f'Banco: {_display_url(url)}')
    if args.command == 'migrate':
        db.upgrade(url)
        print(f'Esquema na revisão {db.head_revision()}')
        return 0
    path = db.sqlite_file(url)
    if path is not None and not path.exists():
        print('Banco inexistente. Execute: python -m app.cli migrate', file=sys.stderr)
        return 1
    engine = db.make_engine(url)
    try:
        if args.command == 'db-status':
            current, head = db.current_revision(engine), db.head_revision()
            print(f'Revisão atual: {current}  esperada: {head}  -> {"OK" if current == head else "MIGRATE NECESSÁRIO"}')
            return 0 if current == head else 1
        db.assert_schema_ready(engine)
        with db.session_factory(engine)() as session:
            if args.command == 'theme-create':
                return _theme_create(session, args)
            if args.command == 'export':
                return _export(session, args)
            created = seed_demo(session)
        print(f'Seed sintético: criados {created}')
        return 0
    except db.SchemaNotReadyError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='python -m app.cli', description='Afrika Reporting — comandos locais')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('migrate', help='aplica migrations pendentes (alembic upgrade head)')
    sub.add_parser('db-status', help='revisão atual do banco x revisão esperada')
    sub.add_parser('seed-demo', help='insere dados sintéticos da demo F00 (idempotente)')
    ins = sub.add_parser('inspect-pptx', help='relatório técnico LOCAL de um PPTX de referência autorizado')
    ins.add_argument('file')
    ins.add_argument('--out', help='diretório do relatório (fora do repositório ou sob output/, private/, data/)')
    ins.add_argument('--privacy', choices=('strict', 'structural'), default='strict',
                     help='strict (padrão): sem nomes; structural: com nomes de masters/layouts/formas. Nunca texto.')
    ins.add_argument('--theme-draft', action='store_true', help='gera rascunho de tema (NÃO aprovado) para revisão')
    ins.add_argument('--wireframes', action='store_true',
                     help='wireframe HTML por slide (caixas, cores e rótulos genéricos; nenhum conteúdo do arquivo)')
    syn = sub.add_parser('synthetic-pptx', help='gera um PPTX SINTÉTICO para testar a inspeção')
    syn.add_argument('file')
    ast = sub.add_parser('theme-asset-add', help='copia logo/fonte para o armazenamento local de ativos (fora do Git)')
    ast.add_argument('file')
    tc = sub.add_parser('theme-create', help='cria tema próprio (ou nova versão) a partir de JSON local')
    tc.add_argument('--key', required=True)
    tc.add_argument('--file', required=True)
    tc.add_argument('--operator', required=True)
    tc.add_argument('--expected-version', type=int)
    ba = sub.add_parser('brand-assets-status',
                        help='F06C: encaixes de ativos do tema × arquivos da pasta local (fora do Git); só metadados')
    ba.add_argument('--theme', required=True)
    ba.add_argument('--version', type=int, required=True)
    ex = sub.add_parser('export', help='F07: exporta a revisão PERSISTIDA de uma apresentação para PPTX ou PDF')
    ex.add_argument('--presentation', required=True)
    ex.add_argument('--revision', type=int, required=True)
    ex.add_argument('--format', choices=('pptx', 'pdf'), required=True)
    ex.add_argument('--out', help='diretório de saída (padrão output/exports; fora do repo ou sob output/, private/)')
    bk = sub.add_parser('backup-db', help='F10: backup local verificado do SQLite (padrão data/backups/)')
    bk.add_argument('--out', help='diretório (fora do repositório ou sob data/ ou private/)')
    rs = sub.add_parser('restore-db', help='F10: restaura um backup verificado (backend PARADO; salva o atual antes)')
    rs.add_argument('file')
    rs.add_argument('--confirm', action='store_true', help='confirma a substituição do banco atual')
    args = parser.parse_args(argv)

    load_project_env()
    if args.command in ('backup-db', 'restore-db'):
        from app import backup
        try:
            out = backup.backup(out=args.out).public() if args.command == 'backup-db' else \
                backup.restore(args.file, confirm=args.confirm)
        except backup.BackupError as exc:
            print(f'Recusado: {exc}', file=sys.stderr)
            return 1
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    if args.command == 'inspect-pptx':
        return _inspect(args)
    if args.command == 'synthetic-pptx':
        from app.presentations import synthetic_pptx
        print(f'PPTX sintético: {synthetic_pptx.build(args.file)}')
        return 0
    if args.command == 'theme-asset-add':
        from app.errors import ApiError
        from app.presentations import assets
        try:
            a = assets.add(Path(args.file).read_bytes())
        except ApiError as exc:
            print(f'Ativo recusado: {exc.message}', file=sys.stderr)
            return 1
        print(json.dumps({'asset_id': a['asset_id'], 'media_type': a['media_type'], 'size_bytes': a['size_bytes'],
                          'dir': str(assets.asset_dir())}, ensure_ascii=False))
        return 0
    if args.command == 'brand-assets-status':
        from app.presentations import brand_assets, themes
        if not themes.builtin_exists(args.theme, args.version):
            print('Use um tema embutido (temas próprios: GET /api/presentation-themes/{key}/versions/{v}).',
                  file=sys.stderr)
            return 1
        defn = themes.load(None, args.theme, args.version)[0]
        status = brand_assets.status(args.theme, [s.name for s in defn.asset_slots])
        print(json.dumps({'dir': str(brand_assets.brand_dir() / args.theme), 'slots': {
            k: {kk: vv for kk, vv in v.items() if kk in ('status', 'media_type', 'sha256', 'size_bytes', 'message')}
            for k, v in status.items()}}, ensure_ascii=False, indent=2))
        return 0
    return _db_command(args)


if __name__ == '__main__':
    raise SystemExit(main())
