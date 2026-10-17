"""Erros da exportação: código estável + mensagem em pt-BR + diagnósticos (nunca valores sensíveis)."""
from __future__ import annotations


class ExportError(Exception):
    """Falha controlada da exportação. `status` = HTTP sugerido quando a falha é detectada antes do job."""

    def __init__(self, code: str, message: str, details: list[dict] | None = None, status: int = 409):
        super().__init__(code)
        self.code, self.message, self.details, self.status = code, message, details or [], status

    def public(self) -> dict:
        return {'code': self.code, 'message': self.message, 'details': self.details[:200]}
