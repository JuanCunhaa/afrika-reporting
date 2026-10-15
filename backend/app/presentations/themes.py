"""Temas visuais (F06A). Só existe um tema DEMONSTRATIVO NEUTRO e PROVISÓRIO: a identidade visual oficial da Afrika
ainda não foi escolhida e nenhuma marca, logo ou template proprietário é reproduzido aqui.

Tokens são nomes de papel (`series.1`, `severity.HIGH`, `text.primary` …); a IR de gráficos referencia tokens e o
renderizador (HTML hoje, PPTX/PDF na F07) os resolve. Trocar a marca = novo tema/versão, sem tocar nos gráficos.
Paleta categórica e rampa ordinal de severidade validadas com o validador de paleta (CVD, contraste, monotonia).
"""
from __future__ import annotations

from app.errors import ApiError

NEUTRAL_DEMO = {
    'id': 'neutral-demo',
    'version': 1,
    'name': 'Tema demonstrativo neutro',
    'provisional': True,
    'notice': 'Tema demonstrativo neutro — PROVISÓRIO. Não representa a identidade visual da Afrika.',
    'canvas': {'width': 1280, 'height': 720, 'aspect_ratio': '16:9', 'unit': 'px'},
    # Fontes genéricas do sistema (sem fonte proprietária). Na exportação PPTX/PDF: equivalente seguro (Arial).
    'fonts': {'heading': 'system-ui, -apple-system, "Segoe UI", Arial, sans-serif',
              'body': 'system-ui, -apple-system, "Segoe UI", Arial, sans-serif',
              'export_fallback': 'Arial'},
    'sizes': {'title': 40, 'subtitle': 22, 'body': 20, 'caption': 14, 'kpi': 56, 'axis': 14, 'label': 14},
    'spacing': {'margin': 56, 'gap': 24},
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
        'gap': '#898781', 'manual': '#7a4b00', 'warning': '#7a4b00', 'delta.up': '#52514e',
        'delta.down': '#52514e',
    },
}

THEMES = {(NEUTRAL_DEMO['id'], NEUTRAL_DEMO['version']): NEUTRAL_DEMO}
SERIES_TOKENS = tuple(f'series.{i}' for i in range(1, 5))


def get_theme(theme_id: str, version: int) -> dict:
    theme = THEMES.get((theme_id, version))
    if theme is None:
        raise ApiError(422, 'unknown_theme', 'Tema inexistente', [{'field': 'theme', 'message': theme_id,
                                                                  'type': 'unknown_theme'}])
    return theme


def public_themes() -> list[dict]:
    return list(THEMES.values())
