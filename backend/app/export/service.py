"""Exportação PPTX/PDF (F07): pré-checagens, renderização, montagem, validação e metadados de proveniência.

Regras:
- Só a revisão PERSISTIDA informada explicitamente (nunca rascunho do editor): o pedido traz `revision`.
- Só com fonte aprovada e referências íntegras: cadeia de revisões + template íntegros, fontes fixadas da revisão
  existentes/aprovadas com conteúdo conferido por hash e nenhum bloqueio na visualização (indicador obrigatório sem
  valor etc.). Caso contrário: 409 com diagnóstico — nenhum arquivo é gerado.
- Overflow: corte real (conteúdo além do padding), vazamento de texto, saída da zona/slide ou reticências bloqueiam a
  exportação com diagnóstico POR SLIDE (nunca truncar em silêncio); conteúdo que só invade o padding vira aviso.
- Fonte do tema indisponível no renderizador (fonte de reserva) bloqueia: layout e PDF não seriam fiéis.
- Nada é recalculado nem consultado na Veracode; snapshots/aprovações não são alterados (só leitura).
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.export import opc, pdf as pdfmod, pptx_builder, render, validate
from app.export.errors import ExportError
from app.export.fonts import FontBook
from app.export.renderer import Renderer, locate
from app.presentations import assets, brand_assets, export_plan, service as presentations, view as viewmod
from app.orm import Presentation, PresentationRevision

FORMATS = {
    'pptx': ('application/vnd.openxmlformats-officedocument.presentationml.presentation', 'pptx'),
    'pdf': ('application/pdf', 'pdf'),
}
MAX_FILE_BYTES = 100 * 2**20
BLOCKING_KINDS = {'spill-x', 'outside-zone', 'outside-slide', 'ellipsis'}
CUT_TOLERANCE_PX = 1.0


@dataclass
class ExportResult:
    data: bytes
    filename: str
    media_type: str
    sha256: str
    report: dict
    warnings: list[dict] = field(default_factory=list)
    timings: dict = field(default_factory=dict)
    engine: dict = field(default_factory=dict)


# ---------------------------------------------------------------- pré-checagens (somente leitura)

def precheck(session: Session, p: Presentation, rev: PresentationRevision) -> dict:
    """Visualização da revisão persistida, se exportável; senão ExportError 409 com os motivos."""
    details: list[dict] = []
    integrity = presentations.verify(session, p, rev.number)
    details += [{'field': 'integrity', 'message': m, 'type': 'integrity_failed'} for m in integrity['problems']]
    sources = json.loads(rev.sources_json)
    if sources.get('policy') != 'APPROVED_ONLY_PINNED' or not sources.get('primary'):
        details.append({'field': 'sources', 'message': 'Revisão sem fonte aprovada fixada', 'type': 'source_not_approved'})
    if details:
        raise ExportError('export_blocked', 'Exportação recusada: fonte não aprovada ou referências não íntegras',
                          details)
    v = viewmod.build(session, p, rev)
    blockers = [{'field': f'slides[{s["index"]}]', 'message': i['message'], 'type': i['code']}
                for s in v['slides'] for i in s['issues'] if i['level'] == 'blocker']
    blockers += [{'field': 'sources', 'message': c['message'], 'type': c['code']}
                 for c in v['checks'] if c['level'] == 'blocker']
    if blockers or not v['ready']:
        raise ExportError('export_blocked', 'Exportação recusada: a apresentação tem bloqueios (veja os detalhes)',
                          blockers)
    return v


# ---------------------------------------------------------------- diagnósticos da renderização

def overflow_diagnostics(findings: list[dict]) -> tuple[list[dict], list[dict]]:
    blocking, warnings = [], []
    for f in findings:
        kind, cut = f['kind'], float(f.get('cut', f['amount']))
        item = {'slide': f['slide'], 'element': f['key'], 'kind': kind, 'px': round(float(f['amount']), 1),
                'hidden_px': round(cut, 1)}
        if kind in ('clipped-x', 'clipped-y'):
            (blocking if cut > CUT_TOLERANCE_PX else warnings).append(item)
        elif kind in BLOCKING_KINDS:
            blocking.append(item)
    return blocking, warnings


def _overflow_message(b: dict) -> str:
    if b['element'].startswith('axis-label:'):  # rótulo de categoria que não coube nem em várias linhas
        return (f'rótulo do eixo "{b["element"].partition(":")[2]}" abreviado no gráfico '
                f'({int(b["px"])} caracteres ocultos); encurte o rótulo ou reduza o número de categorias')
    return f'{b["element"]}: {b["kind"]} de {b["px"]} px ({b["hidden_px"]} px fora da área)'


def font_fallbacks(cap: render.Capture) -> list[dict]:
    """Elementos cujo texto usa família empacotada/declarada (@font-face) mas foi desenhado com fonte do sistema."""
    declared = set(cap.declared_fonts)
    out = []
    for lay in cap.layouts:
        per = cap.fonts.get(lay['index'], {})
        for op in lay['ops']:
            if op['op'] != 'text':
                continue
            wanted = {r['font'] for p in op['paras'] for r in p['runs']} & declared
            if not wanted:
                continue
            used = per.get(str(op.get('xid')), [])
            system = sorted({f['family'] for f in used if not f['custom'] and f.get('glyphs', 0) > 0})
            if system or (wanted - set(cap.webfonts)):
                out.append({'slide': f'{lay["index"]:02d}-{lay["slide_id"]}', 'element': op['key'],
                            'expected': sorted(wanted), 'rendered_with': system or ['(fonte não carregada)']})
    return out


# ---------------------------------------------------------------- nome do arquivo (gerado aqui; nunca do cliente)

def _slug(text: str, limit: int) -> str:
    ascii_ = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]+', '-', ascii_.lower()).strip('-')[:limit].strip('-') or 'apresentacao'


def filename(v: dict, fmt: str) -> str:
    return (f'{_slug(v["owner"]["name"], 40)}_{v["competence"]["competence"]}_{_slug(v["presentation"]["title"], 50)}'
            f'_r{int(v["revision"]["number"])}.{FORMATS[fmt][1]}')


# ---------------------------------------------------------------- montagem

def _images(v: dict, cap: render.Capture) -> dict[str, tuple[bytes, str]]:
    """Bytes dos ativos AUTORIZADOS referenciados pelo layout (lidos do armazenamento local, nunca da página)."""
    out: dict[str, tuple[bytes, str]] = {}
    theme = v['theme']
    images = {img['name']: img for img in theme.get('images', [])}
    for lay in cap.layouts:
        for op in lay['ops']:
            if op['op'] != 'image' or op['key'] in out:
                continue
            kind, _, name = op['key'].partition(':')
            try:
                if kind == 'brand' and name in {a['name'] for a in theme.get('asset_slots', [])}:
                    data, media, _ = brand_assets.read(theme['id'], name)
                    out[op['key']] = (data, media)
                elif kind == 'image' and name in images:
                    data, media = assets.read(images[name]['asset']['asset_id'])
                    out[op['key']] = (data, media)
            except Exception:  # noqa: BLE001 — ativo sumiu entre a renderização e a montagem: encaixe fica vazio
                continue
    return out


def provenance(v: dict, cap: render.Capture, renderer: Renderer) -> dict[str, str]:
    t, th, r, src = v['template'], v['theme'], v['revision'], v['sources']['primary']
    return {
        'afrika.generator': pptx_builder.GENERATOR,
        'afrika.presentation': v['presentation']['id'],
        'afrika.revision': str(r['number']),
        'afrika.revision_hash': r['revision_hash'],
        'afrika.document_hash': r['document_hash'],
        'afrika.sources_hash': r['sources_hash'],
        'afrika.template': f'{t["key"]}@{t["version"]}',
        'afrika.template_hash': t.get('definition_hash', ''),
        'afrika.theme': f'{th["id"]}@{th["version"]}',
        'afrika.theme_hash': th['definition_hash'],
        'afrika.owner': f'{v["owner"]["kind"]}:{v["owner"]["id"]}',
        'afrika.competence': v['competence']['competence'],
        'afrika.primary_source': f'competência {src["competence"]} revisão {src["revision"]} aprovação '
                                 f'{src["approval_sequence"]} ({src["content_hash"][:16]}…)',
        'afrika.data_policy': 'Somente revisões aprovadas fixadas; nenhum número recalculado ou interpolado.',
        'afrika.severity_labels': v.get('severity_labels', 'veracode'),
        'afrika.export_plan_version': str(export_plan.PLAN_VERSION),
        'afrika.layout_version': str(render.LAYOUT_VERSION),
        'afrika.renderer_source_hash': renderer.source_hash,
        'afrika.render_engine': f'{cap.engine.get("product")} ({cap.engine.get("source")})',
    }


def build_export(v: dict, fmt: str, *, renderer: Renderer | None = None, environ: dict | None = None,
                 timeout: float = 120.0, block_fonts: bool = False) -> ExportResult:
    if fmt not in FORMATS:
        raise ExportError('export_format_invalid', 'Formato de exportação inválido', status=422)
    t0 = time.monotonic()
    renderer = renderer or locate(environ)
    plan = export_plan.plan(v)
    cap = render.capture(renderer, v, pdf=fmt == 'pdf', timeout=timeout, environ=environ, block_fonts=block_fonts)
    blocking, warn_overflow = overflow_diagnostics(cap.overflow)
    if blocking:
        raise ExportError('content_overflow', 'Conteúdo não cabe no slide: exportação bloqueada para não truncar '
                                              'texto. Reduza ou divida o conteúdo dos slides indicados.',
                          [{'field': b['slide'], 'message': _overflow_message(b), 'type': b['kind']}
                           for b in blocking])
    fallbacks = font_fallbacks(cap)
    if fallbacks:
        raise ExportError('font_unavailable', 'Fontes do tema indisponíveis no renderizador (o texto sairia com fonte '
                                              'de reserva). Refaça o build do frontend ou verifique os ativos do tema.',
                          [{'field': f['slide'], 'message': f'{f["element"]}: esperado {", ".join(f["expected"])}; '
                                                            f'renderizado com {", ".join(f["rendered_with"])}',
                            'type': 'font_fallback'} for f in fallbacks[:50]])
    if cap.blocked:
        raise ExportError('render_request_blocked', 'A página de renderização tentou acessar recursos não '
                                                    'autorizados', [{'field': 'render', 'message': b,
                                                                     'type': 'blocked'} for b in cap.blocked[:20]])
    warnings = [{'code': 'content_tight', 'message': f'{w["slide"]} · {w["element"]}: conteúdo encosta na borda '
                                                      f'(invade {w["px"]} px do recuo interno, sem corte)'}
                for w in warn_overflow]
    ts = pptx_builder._ts(v)
    if fmt == 'pptx':
        book = FontBook(renderer.dist)
        built = pptx_builder.build(pptx_builder.BuildInput(view=v, layouts=cap.layouts, fontbook=book,
                                                           images=_images(v, cap), rasters=cap.rasters))
        fonts = opc.embed_fonts(built.prs, built.faces, book)
        opc.add_custom_properties(built.prs, provenance(v, cap, renderer))
        buf = io.BytesIO()
        built.prs.save(buf)
        data = opc.normalize(buf.getvalue(), ts)
        report = validate.pptx(data, v, built.manifest, plan)
        report['fonts'] = fonts
        warnings += [{'code': w['code'], 'message': w['message']} for w in built.warnings]
        if fonts['not_embedded']:
            warnings.append({'code': 'font_not_embedded', 'message': 'Fontes referenciadas pelo nome (sem arquivo local '
                             'para incorporar): ' + ', '.join(sorted({f['typeface'] for f in fonts['not_embedded']}))})
    else:
        data = pdfmod.normalize(cap.pdf or b'', ts)
        # famílias exigidas só quando o tema usa APENAS fontes empacotadas (Afrika); tema com fonte do sistema (neutro)
        # varia por plataforma: confere-se só que tudo foi incorporado
        theme_fams = {v['theme']['fonts'][r]['stack'][0] for r in ('heading', 'body', 'numeric')}
        expected = theme_fams if theme_fams <= set(cap.declared_fonts) else None
        report = {'pdf': pdfmod.validate(data, slides=len(v['slides']), canvas=v['theme']['canvas'],
                                         expected_families=expected)}
    if len(data) > MAX_FILE_BYTES:
        raise ExportError('export_too_large', 'Arquivo gerado maior que o limite', status=413)
    timings = {**cap.timings, 'total_s': round(time.monotonic() - t0, 3)}
    report.update({'slides': len(v['slides']), 'overflow_warnings': len(warn_overflow),
                   'renderer': {'source_hash': renderer.source_hash, 'stamp_check': renderer.stamp_check},
                   'engine': cap.engine})
    return ExportResult(data=data, filename=filename(v, fmt), media_type=FORMATS[fmt][0],
                        sha256=hashlib.sha256(data).hexdigest(), report=report, warnings=warnings, timings=timings,
                        engine=cap.engine)
