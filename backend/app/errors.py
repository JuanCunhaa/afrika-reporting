"""Formato único de erro da API e handlers que NUNCA ecoam valores enviados.

Corpo: {"error": {"code": str, "message": str, "details": [{"field", "message", "type"}]}}
- 400: JSON malformado ou regra de negócio sobre entrada bem-formada (referência inexistente, aninhamento).
- 404: recurso inexistente.
- 409: conflito de unicidade ou de estado (exclusão bloqueada).
- 422: validação de schema (tipos, tamanhos, campos extras, UUID inválido).
O `input` e o `ctx` do Pydantic são descartados: um segredo colado por engano não volta na resposta.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger('afrika.api')


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(code)
        self.status, self.code, self.message = status, code, message


_NOT_FOUND = {'client': 'Cliente não encontrado', 'subclient': 'Subcliente não encontrado',
              'connection': 'Conexão não encontrada'}


def not_found(entity: str) -> ApiError:
    return ApiError(404, f'{entity}_not_found', _NOT_FOUND[entity])


def conflict(code: str, message: str) -> ApiError:
    return ApiError(409, code, message)


def bad_request(code: str, message: str) -> ApiError:
    return ApiError(400, code, message)


def _body(code: str, message: str, details: list | None = None) -> dict:
    return {'error': {'code': code, 'message': message, 'details': details or []}}


def _field(loc: tuple) -> str:
    return '.'.join(str(p) for p in loc)


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_req: Request, exc: ApiError):
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_req: Request, exc: RequestValidationError):
        errors = exc.errors()
        if any(e.get('type') == 'json_invalid' for e in errors):
            return JSONResponse(_body('malformed_json', 'Corpo da requisição não é um JSON válido'), status_code=400)
        details = [{'field': _field(e.get('loc', ())), 'message': e.get('msg', ''), 'type': e.get('type', '')}
                   for e in errors]
        return JSONResponse(_body('validation_error', 'Dados inválidos', details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_req: Request, exc: StarletteHTTPException):
        code = {404: 'not_found', 405: 'method_not_allowed'}.get(exc.status_code, 'http_error')
        message = exc.detail if isinstance(exc.detail, str) else 'Erro HTTP'
        return JSONResponse(_body(code, message), status_code=exc.status_code, headers=getattr(exc, 'headers', None))

    @app.exception_handler(Exception)
    async def _unhandled(req: Request, exc: Exception):
        # Somente o tipo da exceção: mensagens de driver podem conter dados.
        logger.error('erro não tratado %s em %s %s', type(exc).__name__, req.method, req.url.path)
        return JSONResponse(_body('internal_error', 'Erro interno'), status_code=500)
