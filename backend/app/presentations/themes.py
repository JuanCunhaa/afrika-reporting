"""Temas visuais versionados (F06A → F06B.1).

Um tema é um conjunto TIPADO e COMPLETO de tokens visuais: paleta, fontes e pesos, tamanhos tipográficos, entrelinhas,
espaçamentos, raios e bordas, regiões (posicionamento de cabeçalho/conteúdo/rodapé), cabeçalho e rodapé, capa e
encerramento, fundos, imagens (logotipos) por referência a ativo local, formato dos gráficos e dimensões do slide.
Os componentes (HTML hoje; PPTX/PDF na F07) só leem tokens: nenhum valor visual fica codificado neles.

- Versão de tema é IMUTÁVEL (append-only). Mudança = nova versão; templates apontam para `{id, version}` e cada
  cliente/subcliente escolhe seu template — logo, temas diferentes por cliente.
- Temas embutidos ficam no código (`BUILTIN`); temas próprios (ex.: o oficial derivado do PPTX aprovado) ficam SÓ no
  banco local e seus ativos (logos/fontes) num diretório local fora do Git (`assets.py`). Nada proprietário é versionado.
- O único tema embutido é o DEMONSTRATIVO NEUTRO e PROVISÓRIO da F06A (`neutral-demo@1`): não representa a identidade
  visual da Afrika.
- Paleta categórica e rampa ordinal de severidade do tema neutro validadas com o validador de paleta (F06A).
"""
from __future__ import annotations

import json
import math
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError, conflict

SERIES_TOKENS = tuple(f'series.{i}' for i in range(1, 5))
SEVERITY_TOKENS = tuple(f'severity.{k}' for k in ('VERY_HIGH', 'HIGH', 'MEDIUM', 'LOW', 'VERY_LOW', 'INFORMATIONAL',
                                                  'UNKNOWN'))
# Tokens de cor que todo tema precisa definir (a IR de gráficos e os componentes referenciam estes nomes).
REQUIRED_COLORS = ('surface', 'page', 'band', 'text.primary', 'text.secondary', 'text.muted', 'grid', 'axis',
                   'border', 'accent', *SERIES_TOKENS, *SEVERITY_TOKENS, 'gap', 'manual', 'warning', 'delta.up',
                   'delta.down')
GENERIC_FAMILIES = ('system-ui', '-apple-system', 'sans-serif', 'serif', 'monospace', 'ui-sans-serif', 'ui-serif')
ASSET_MEDIA = ('image/png', 'image/jpeg', 'image/svg+xml', 'font/woff2', 'font/woff', 'font/ttf', 'font/otf')

ThemeKey = Annotated[str, StringConstraints(min_length=2, max_length=60, pattern=r'^[a-z0-9][a-z0-9-]*$')]
ColorHex = Annotated[str, StringConstraints(pattern=r'^#[0-9a-fA-F]{6}$')]
ColorToken = Annotated[str, StringConstraints(min_length=1, max_length=40,
                                              pattern=r'^[a-z][a-z0-9]*([._-][A-Za-z0-9]+)*$')]
# Nome de família sem aspas, vírgulas, ponto e vírgula ou chaves: seguro para CSS e para o PPTX.
Family = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80,
                                          pattern=r'^-?[A-Za-z0-9][A-Za-z0-9 _-]*$')]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300, pattern=r'^[^\x00-\x1f\x7f<>]*$')]
Px = Annotated[float, Field(ge=0, le=4000)]
Pos = Annotated[float, Field(gt=0, le=4000)]
Ratio = Annotated[float, Field(gt=0, le=20)]
Weight = Annotated[int, Field(ge=100, le=900)]
LineHeight = Annotated[float, Field(ge=0.8, le=3)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Box(_Strict):
    x: Px
    y: Px
    w: Pos
    h: Pos


class Insets(_Strict):
    top: Px
    right: Px
    bottom: Px
    left: Px


class AssetRef(_Strict):
    asset_id: Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]
    media_type: Literal[ASSET_MEDIA]  # type: ignore[valid-type]


class FontSpec(_Strict):
    stack: list[Family] = Field(min_length=1, max_length=8)  # ordem de preferência; termine com família genérica
    export_family: Family = 'Arial'  # nome gravado no PPTX/PDF (F07) quando a fonte do tema não existir lá
    asset: AssetRef | None = None  # arquivo de fonte local (woff2/woff/ttf/otf) para a 1ª família da pilha


class Fonts(_Strict):
    heading: FontSpec
    body: FontSpec
    numeric: FontSpec


class Weights(_Strict):
    title: Weight = 650
    cover_title: Weight = 700
    kpi_value: Weight = 650
    chart_title: Weight = 600
    value_label: Weight = 600
    emphasis: Weight = 600


class Sizes(_Strict):
    base: Px = 16
    cover_kicker: Px = 22
    cover_title: Px = 56
    cover_subtitle: Px = 26
    cover_meta: Px = 20
    title: Px = 38
    subtitle: Px = 21
    body: Px = 20
    bullet: Px = 21
    caption: Px = 15
    footer: Px = 13
    presenters: Px = 19
    kpi_label: Px = 17
    kpi_value: Px = 52
    kpi_value_compact: Px = 34
    kpi_value_missing: Px = 30
    kpi_unit: Px = 15
    tag: Px = 12
    table: Px = 18
    table_header: Px = 15
    ranking: Px = 17
    chart_title: Px = 19
    axis: Px = 14
    value_label: Px = 15
    gap_label: Px = 13
    legend: Px = 15
    note: Px = 14
    severity: Px = 18
    unavailable: Px = 19
    unavailable_note: Px = 14


class LineHeights(_Strict):
    title: LineHeight = 1.15
    cover_title: LineHeight = 1.1
    body: LineHeight = 1.45
    bullet: LineHeight = 1.45
    kpi_value: LineHeight = 1.0


class Spacing(_Strict):
    block_gap: Px = 16
    column_gap: Px = 28
    paragraph_gap: Px = 10
    subtitle_gap: Px = 6
    bullet_indent: Px = 28
    bullet_gap: Px = 8
    card_gap: Px = 20
    card_gap_compact: Px = 12
    card_padding_y: Px = 20
    card_padding_x: Px = 22
    card_inner_gap: Px = 6
    table_cell_y: Px = 8
    table_cell_x: Px = 10
    ranking_cell_y: Px = 6
    legend_gap: Px = 18
    reco_gap: Px = 36
    presenters_top: Px = 16
    presenters_gap: Px = 6
    chart_gap: Px = 8
    severity_gap: Px = 12
    severity_top: Px = 8
    severity_col_gap: Px = 14
    footer_gap: Px = 24
    footer_padding_top: Px = 8
    unavailable_padding: Px = 28
    unavailable_gap: Px = 8
    tag_gap: Px = 6
    tag_padding_y: Px = 1
    tag_padding_x: Px = 8
    marker_padding_x: Px = 6
    kicker_letter_spacing_em: Annotated[float, Field(ge=0, le=1)] = 0.08


class Radii(_Strict):
    card: Px = 12
    small: Px = 6
    bar: Px = 4
    swatch: Px = 3
    track: Px = 4
    pill: Px = 999


class Borders(_Strict):
    card: Px = 1
    header_rule: Px = 2
    row_rule: Px = 1
    unavailable: Px = 2
    footer_rule: Px = 1
    tag: Px = 1
    marker: Px = 1


class FooterBox(_Strict):
    """Rodapé ancorado na base (altura = conteúdo): `bottom` é a distância da base do slide; `reserve` é a altura
    reservada para validação de sobreposição com o conteúdo."""
    x: Px
    w: Pos
    bottom: Px
    reserve: Px


class LayoutRegions(_Strict):
    """`flow`: título, conteúdo e legenda empilhados dentro de `body` (F06A). `fixed`: título em `header` e
    conteúdo+legenda em `content`, posições independentes (equivalente a placeholders de um master PPTX)."""
    mode: Literal['flow', 'fixed'] = 'flow'
    body: Box
    header: Box | None = None
    content: Box | None = None
    footer: FooterBox
    visual_side_ratio: tuple[Ratio, Ratio] = (2, 1)  # gráfico : texto nos layouts *-with-text
    summary_ratio: tuple[Ratio, Ratio] = (1.6, 1)  # texto : destaques no sumário


class Background(_Strict):
    color: ColorToken | None = None
    image: AssetRef | None = None
    fit: Literal['cover', 'contain'] = 'cover'


class LayoutOverride(_Strict):
    mode: Literal['flow', 'fixed'] | None = None
    body: Box | None = None
    header: Box | None = None
    content: Box | None = None
    background: Background | None = None
    hide_footer: bool = False


class Header(_Strict):
    accent_bar: bool = True
    accent_width: Px = 6
    accent_color: ColorToken = 'accent'
    padding_left: Px = 16
    align: Literal['left', 'center'] = 'left'


FooterItem = Literal['owner_competence', 'source', 'provisional', 'page', 'custom_text']


class Footer(_Strict):
    show: bool = True
    items: list[FooterItem] = Field(default_factory=lambda: ['owner_competence', 'source', 'provisional', 'page'],
                                    max_length=6)
    separator: bool = True
    custom_text: Text | None = None


class Cover(_Strict):
    band: Literal['left', 'top', 'none'] = 'left'
    band_size: Px = 28
    band_color: ColorToken = 'accent'
    padding: Insets = Field(default_factory=lambda: Insets(top=120, right=96, bottom=120, left=96))
    gap: Px = 16
    meta_top: Px = 12
    align: Literal['left', 'center'] = 'left'
    kicker_uppercase: bool = True


class Closing(_Strict):
    padding: Insets = Field(default_factory=lambda: Insets(top=96, right=96, bottom=96, left=96))
    gap: Px = 16
    align: Literal['left', 'center'] = 'left'


class Backgrounds(_Strict):
    default: Background = Field(default_factory=lambda: Background(color='surface'))
    cover: Background | None = None
    closing: Background | None = None


SlideScope = Literal['all', 'cover', 'closing', 'content']


class ImageSlot(_Strict):
    name: Annotated[str, StringConstraints(min_length=1, max_length=40, pattern=r'^[a-z0-9][a-z0-9-]*$')]
    asset: AssetRef
    box: Box
    slides: list[SlideScope] = Field(default_factory=lambda: ['all'], min_length=1, max_length=4)
    fit: Literal['contain', 'cover'] = 'contain'
    alt: Text = ''


class Charts(_Strict):
    plot_width: Pos = 1100  # viewBox do gráfico em layout cheio (px do canvas)
    plot_height: Pos = 400
    plot_width_with_text: Pos = 1100  # viewBox no layout com texto lateral
    plot_padding: Insets = Field(default_factory=lambda: Insets(top=24, right=24, bottom=56, left=64))
    plot_max_height: Pos = 420
    y_ticks: Annotated[int, Field(ge=2, le=10)] = 4  # divisões do eixo Y (linhas de grade = y_ticks + 1)
    bar_max_width: Pos = 56
    bar_width_ratio: Annotated[float, Field(gt=0, le=1)] = 0.6
    bar_radius: Px = 4
    gap_dash: Annotated[str, StringConstraints(pattern=r'^\d{1,2}( \d{1,2}){1,3}$')] = '6 4'
    gap_bar_ratio: Annotated[float, Field(gt=0, le=1)] = 0.4
    line_width: Pos = 2.5
    point_radius: Pos = 6
    point_stroke: Px = 2
    axis_label_offset: Px = 10
    category_label_offset: Px = 22
    value_label_offset: Px = 8
    point_label_offset: Px = 12
    severity_label_width: Pos = 190
    severity_value_width: Pos = 90
    severity_bar_height: Pos = 26
    rank_bar_height: Pos = 12
    rank_bar_max: Pos = 160
    swatch_size: Pos = 14
    swatch_gap: Px = 6
    swatch_baseline_offset: Annotated[float, Field(ge=-20, le=20)] = -2
    rank_bar_gap: Px = 10
    min_bar: Px = 2
    grid_width: Pos = 1
    gap_line_dash: Annotated[str, StringConstraints(pattern=r'^\d{1,2}( \d{1,2}){1,3}$')] = '4 6'
    axis_label_baseline: Annotated[float, Field(ge=-40, le=40)] = 5
    unit_label_y: Px = 14
    gap_label_y_offset: Px = 14
    texture_stripe: Pos = 5
    texture_period: Pos = 8
    texture_opacity: Annotated[float, Field(ge=0, le=1)] = 0.55
    legend_position: Literal['top', 'bottom'] = 'top'


class Canvas(_Strict):
    width: Annotated[int, Field(ge=320, le=3840)]
    height: Annotated[int, Field(ge=180, le=2160)]


class ThemeDefinition(_Strict):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120,
                                           pattern=r'^[^\x00-\x1f\x7f<>]*$')]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ''
    provisional: bool = True
    notice: Text = ''
    canvas: Canvas
    colors: dict[ColorToken, ColorHex]
    fonts: Fonts
    weights: Weights = Field(default_factory=Weights)
    sizes: Sizes = Field(default_factory=Sizes)
    line_heights: LineHeights = Field(default_factory=LineHeights)
    spacing: Spacing = Field(default_factory=Spacing)
    radii: Radii = Field(default_factory=Radii)
    borders: Borders = Field(default_factory=Borders)
    layout: LayoutRegions
    layouts: dict[Annotated[str, StringConstraints(pattern=r'^[a-z][a-z-]*$', max_length=40)], LayoutOverride] = \
        Field(default_factory=dict)
    header: Header = Field(default_factory=Header)
    footer: Footer = Field(default_factory=Footer)
    cover: Cover = Field(default_factory=Cover)
    closing: Closing = Field(default_factory=Closing)
    backgrounds: Backgrounds = Field(default_factory=Backgrounds)
    images: list[ImageSlot] = Field(default_factory=list, max_length=8)
    charts: Charts = Field(default_factory=Charts)

    @model_validator(mode='after')
    def _coherent(self) -> ThemeDefinition:
        errors = theme_errors(self)
        if errors:
            raise ValueError('; '.join(errors))
        return self



def _inside(box: Box, canvas: Canvas) -> bool:
    return box.x + box.w <= canvas.width + 0.01 and box.y + box.h <= canvas.height + 0.01


def theme_errors(t: ThemeDefinition) -> list[str]:
    """Coerência além dos tipos: tokens obrigatórios, referências de cor, regiões dentro do canvas e sem invadir o
    rodapé, pilhas de fonte terminando em família genérica e ativos de fonte só em mídia de fonte."""
    from app.presentations.catalog import SLIDE_TYPES  # import tardio: catalog não depende de temas

    out = []
    missing = [c for c in REQUIRED_COLORS if c not in t.colors]
    if missing:
        out.append('cores obrigatórias ausentes: ' + ', '.join(missing))
    refs = [('header.accent_color', t.header.accent_color), ('cover.band_color', t.cover.band_color)]
    bgs = [('backgrounds.default', t.backgrounds.default), ('backgrounds.cover', t.backgrounds.cover),
           ('backgrounds.closing', t.backgrounds.closing)]
    bgs += [(f'layouts.{k}.background', o.background) for k, o in t.layouts.items()]
    refs += [(f'{name}.color', bg.color) for name, bg in bgs if bg is not None and bg.color is not None]
    out += [f'{name}: cor "{tok}" não definida em colors' for name, tok in refs if tok not in t.colors]
    for role in ('heading', 'body', 'numeric'):
        spec: FontSpec = getattr(t.fonts, role)
        if spec.stack[-1] not in GENERIC_FAMILIES:
            out.append(f'fonts.{role}.stack deve terminar com família genérica ({", ".join(GENERIC_FAMILIES)})')
        if spec.asset is not None and not spec.asset.media_type.startswith('font/'):
            out.append(f'fonts.{role}.asset deve ser arquivo de fonte')
    for img in t.images:
        if not img.asset.media_type.startswith('image/'):
            out.append(f'images.{img.name}: ativo deve ser imagem')
        if not _inside(img.box, t.canvas):
            out.append(f'images.{img.name}: caixa fora do canvas')
    if len({i.name for i in t.images}) != len(t.images):
        out.append('images: nomes repetidos')
    footer_top = t.canvas.height - t.layout.footer.bottom - t.layout.footer.reserve
    known_layouts = {lay for s in SLIDE_TYPES.values() for lay in s.layouts}
    regions = [('layout', t.layout.mode, t.layout.body, t.layout.header, t.layout.content)]
    for k, o in t.layouts.items():
        if k not in known_layouts:
            out.append(f'layouts.{k}: layout inexistente no catálogo')
        regions.append((f'layouts.{k}', o.mode or t.layout.mode, o.body or t.layout.body,
                        o.header or t.layout.header, o.content or t.layout.content))
    for name, mode, body, header, content in regions:
        boxes = [('body', body)] if mode == 'flow' else [('header', header), ('content', content)]
        for bname, box in boxes:
            if box is None:
                out.append(f'{name}.{bname}: obrigatório no modo {mode}')
                continue
            if not _inside(box, t.canvas):
                out.append(f'{name}.{bname}: caixa fora do canvas')
            if t.footer.show and box.y + box.h > footer_top + 0.01:
                out.append(f'{name}.{bname}: invade a área reservada ao rodapé (y+h > {footer_top:g})')
    if t.layout.footer.x + t.layout.footer.w > t.canvas.width + 0.01:
        out.append('layout.footer: fora do canvas')
    if 'custom_text' in t.footer.items and not t.footer.custom_text:
        out.append('footer.custom_text: obrigatório quando o item custom_text é usado')
    return out


# ---------------------------------------------------------------- tema embutido (demonstrativo, provisório)

_SYSTEM_STACK = ['system-ui', '-apple-system', 'Segoe UI', 'Arial', 'sans-serif']

# Conversão do tema neutro da F06A para o esquema completo. Os valores efetivos são os que o renderizador da F06A
# aplicava (conversão verificada por regressão visual: 19/19 slides idênticos pixel a pixel), com DUAS correções
# deliberadas e documentadas em docs/THEMES.md: (1) a região de conteúdo terminava dentro do rodapé (legenda sobreposta
# ao rodapé) — agora termina 12 px acima dele (rodapé medido: 28 px); (2) o gráfico no layout com texto lateral era
# reduzido a ~69% (eixos ilegíveis) — agora o viewBox acompanha a largura real (760 px). A partir da F06B.1 esta versão
# é imutável (hash fixado em teste).
NEUTRAL_DEMO_V1: dict = {
    'name': 'Tema demonstrativo neutro',
    'description': 'Tema sintético da F06A. Não representa a identidade visual da Afrika.',
    'provisional': True,
    'notice': 'Tema demonstrativo neutro — PROVISÓRIO. Não representa a identidade visual da Afrika.',
    'canvas': {'width': 1280, 'height': 720},
    'colors': {
        'surface': '#fcfcfb', 'page': '#f9f9f7', 'band': '#eef1f4',
        'text.primary': '#0b0b0b', 'text.secondary': '#52514e', 'text.muted': '#6f6d68',
        'grid': '#e1e0d9', 'axis': '#c3c2b7', 'border': '#d9d8d2',
        'accent': '#2a78d6',
        'series.1': '#2a78d6', 'series.2': '#eb6834', 'series.3': '#1baf7a', 'series.4': '#eda100',
        # Severidade: rampa ordinal de UM tom (mais escura = mais severa); desconhecida = cinza com textura.
        'severity.VERY_HIGH': '#5a1508', 'severity.HIGH': '#842510', 'severity.MEDIUM': '#ab3d1b',
        'severity.LOW': '#cc5d30', 'severity.VERY_LOW': '#e07e52', 'severity.INFORMATIONAL': '#ec9b76',
        'severity.UNKNOWN': '#898781',
        'gap': '#898781', 'manual': '#7a4b00', 'warning': '#7a4b00', 'delta.up': '#52514e', 'delta.down': '#52514e',
    },
    # Fontes genéricas do sistema (sem fonte proprietária). Na exportação PPTX/PDF: equivalente seguro (Arial).
    'fonts': {role: {'stack': _SYSTEM_STACK, 'export_family': 'Arial'} for role in ('heading', 'body', 'numeric')},
    'layout': {'mode': 'flow', 'body': {'x': 56, 'y': 48, 'w': 1168, 'h': 584},
               'footer': {'x': 56, 'w': 1168, 'bottom': 48, 'reserve': 28}},
    'charts': {'plot_width_with_text': 760},
    'backgrounds': {'default': {'color': 'surface'}, 'closing': {'color': 'band'}},
}

BUILTIN: dict[tuple[str, int], dict] = {('neutral-demo', 1): NEUTRAL_DEMO_V1}


# ---------------------------------------------------------------- consulta e escrita

def parse(raw: dict) -> ThemeDefinition:
    try:
        return ThemeDefinition.model_validate(raw)
    except ValidationError as exc:  # sem `input`: nada do que foi enviado volta na resposta
        raise ApiError(422, 'invalid_theme', 'Tema inválido',
                       [{'field': '.'.join(str(x) for x in e['loc']) or 'theme', 'message': e['msg'],
                         'type': e['type']} for e in exc.errors()[:100]]) from None


def definition_hash(defn: ThemeDefinition) -> str:
    from app.snapshots.values import sha256
    return sha256(defn.model_dump(mode='json'))


_BUILTIN_PARSED: dict[tuple[str, int], ThemeDefinition] = {k: parse(v) for k, v in BUILTIN.items()}


def aspect_ratio(canvas: Canvas) -> str:
    g = math.gcd(canvas.width, canvas.height)
    return f'{canvas.width // g}:{canvas.height // g}'


def _public(key: str, version: int, defn: ThemeDefinition, origin: str, extra: dict | None = None) -> dict:
    out = {'id': key, 'version': version, 'origin': origin, 'definition_hash': definition_hash(defn),
           **defn.model_dump(mode='json'), **(extra or {})}
    out['canvas']['aspect_ratio'] = aspect_ratio(defn.canvas)  # derivado (não faz parte da definição/hash)
    return out


def builtin_exists(key: str, version: int) -> bool:
    return (key, version) in _BUILTIN_PARSED


def _row(session: Session, key: str, version: int | None = None):
    from app.orm import PresentationTheme
    q = select(PresentationTheme).where(PresentationTheme.theme_key == key)
    q = q.where(PresentationTheme.version == version) if version is not None else \
        q.order_by(PresentationTheme.version.desc()).limit(1)
    return session.scalar(q)


def exists(session: Session | None, key: str, version: int) -> bool:
    return builtin_exists(key, version) or (session is not None and _row(session, key, version) is not None)


def load(session: Session | None, key: str, version: int) -> tuple[ThemeDefinition, dict]:
    """(definição, tema público) — embutido no código ou próprio no banco local."""
    if (key, version) in _BUILTIN_PARSED:
        defn = _BUILTIN_PARSED[(key, version)]
        return defn, _public(key, version, defn, 'BUILTIN')
    row = None if session is None else _row(session, key, version)
    if row is None:
        raise ApiError(422, 'unknown_theme', 'Tema inexistente', [{'field': 'theme', 'message': key,
                                                                  'type': 'unknown_theme'}])
    defn = ThemeDefinition.model_validate(json.loads(row.definition_json))
    return defn, _public(key, version, defn, 'CUSTOM', {'created_by': row.created_by,
                                                        'created_at': row.created_at.isoformat()})


def resolve(session: Session | None, key: str, version: int) -> dict:
    """Tema público (definição completa + identificação)."""
    return load(session, key, version)[1]


def get_theme(theme_id: str, version: int) -> dict:
    """Compatibilidade F06A: só temas embutidos (sem sessão)."""
    return resolve(None, theme_id, version)


def list_all(session: Session) -> list[dict]:
    from app.orm import PresentationTheme
    out = [{'id': k, 'version': v, 'name': d.name, 'provisional': d.provisional, 'origin': 'BUILTIN',
            'versions': [v], 'definition_hash': definition_hash(d)} for (k, v), d in _BUILTIN_PARSED.items()]
    rows = session.scalars(select(PresentationTheme).order_by(PresentationTheme.theme_key,
                                                              PresentationTheme.version)).all()
    by_key: dict[str, list] = {}
    for r in rows:
        by_key.setdefault(r.theme_key, []).append(r)
    for key, vs in by_key.items():
        last = vs[-1]
        out.append({'id': key, 'version': last.version, 'name': last.name, 'provisional': last.provisional,
                    'origin': 'CUSTOM', 'versions': [v.version for v in vs], 'definition_hash': last.definition_hash})
    return out


def public_themes() -> list[dict]:
    return [_public(k, v, d, 'BUILTIN') for (k, v), d in _BUILTIN_PARSED.items()]


def asset_refs(defn: ThemeDefinition) -> list[AssetRef]:
    refs = [img.asset for img in defn.images]
    refs += [getattr(defn.fonts, r).asset for r in ('heading', 'body', 'numeric') if getattr(defn.fonts, r).asset]
    bgs = [defn.backgrounds.default, defn.backgrounds.cover, defn.backgrounds.closing,
           *(o.background for o in defn.layouts.values())]
    refs += [bg.image for bg in bgs if bg is not None and bg.image is not None]
    return refs


def missing_assets(defn: ThemeDefinition) -> list[str]:
    from app.presentations import assets
    return sorted({r.asset_id for r in asset_refs(defn) if not assets.exists(r.asset_id, r.media_type)})


def _insert(session: Session, key: str, version: int, defn: ThemeDefinition, operator: str):
    from app.orm import PresentationTheme
    from app.snapshots import audit
    from app.snapshots.values import canonical
    row = PresentationTheme(id=uuid.uuid4(), theme_key=key, version=version, name=defn.name,
                            provisional=defn.provisional, definition_json=canonical(defn.model_dump(mode='json')),
                            definition_hash=definition_hash(defn), created_by=operator)
    session.add(row)
    session.flush()
    audit.append(session, 'theme.version_created', actor=operator,
                 details={'theme': key, 'version': version, 'definition_hash': row.definition_hash})
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise conflict('theme_conflict', 'Outra versão do tema foi publicada ao mesmo tempo; recarregue') from None
    return row


def _check_assets(defn: ThemeDefinition) -> None:
    missing = missing_assets(defn)
    if missing:
        raise ApiError(422, 'theme_asset_missing', 'Ativo do tema não encontrado no armazenamento local',
                       [{'field': 'assets', 'message': m, 'type': 'theme_asset_missing'} for m in missing])


def create(session: Session, key: str, raw: dict, operator: str) -> dict:
    if any(k == key for k, _ in _BUILTIN_PARSED):
        raise conflict('builtin_theme_readonly', 'Chave reservada a tema embutido: escolha outra chave')
    defn = parse(raw)
    _check_assets(defn)
    if _row(session, key) is not None:
        raise conflict('theme_exists', 'Já existe tema com esta chave: publique uma nova versão')
    _insert(session, key, 1, defn, operator)
    return resolve(session, key, 1)


def create_version(session: Session, key: str, raw: dict, operator: str, expected_version: int) -> dict:
    if any(k == key for k, _ in _BUILTIN_PARSED):
        raise conflict('builtin_theme_readonly', 'Temas embutidos não recebem versões pela API')
    current = _row(session, key)
    if current is None:
        raise ApiError(404, 'theme_not_found', 'Tema não encontrado')
    if current.version != expected_version:
        raise conflict('theme_conflict', f'O tema está na versão {current.version}, não {expected_version}')
    defn = parse(raw)
    _check_assets(defn)
    if definition_hash(defn) == current.definition_hash:
        raise conflict('theme_unchanged', 'Definição idêntica à versão vigente')
    from app.orm import PresentationTheme
    number = (session.scalar(select(func.max(PresentationTheme.version))
                             .where(PresentationTheme.theme_key == key)) or 0) + 1
    _insert(session, key, number, defn, operator)
    return resolve(session, key, number)
