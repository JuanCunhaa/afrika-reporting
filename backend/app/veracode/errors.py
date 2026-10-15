"""Erros da integração Veracode. Mensagens fixas, nunca derivadas de respostas, URLs, headers ou segredos."""
from __future__ import annotations

# code -> (status HTTP devolvido pela NOSSA API, mensagem para o operador)
CATALOG: dict[str, tuple[int, str]] = {
    'connection_not_configured': (409, 'Escopo sem conexão Veracode (nem própria, nem herdada do cliente)'),
    'credentials_missing': (409, 'Credenciais da referência desta conexão não estão configuradas no ambiente do '
                                 'backend'),
    'credentials_invalid_format': (409, 'Credenciais da referência desta conexão estão em formato inválido no '
                                        'ambiente do backend'),
    'unsupported_credential_ref': (409, 'Referência de credencial não suportada (use env:NOME)'),
    'auth_failed': (502, 'Veracode recusou a autenticação (HTTP 401): credencial inválida, revogada ou de outra '
                         'região'),
    'forbidden': (502, 'Permissão insuficiente na Veracode para este recurso (HTTP 403): revise os papéis da '
                       'conta de API'),
    'not_found': (502, 'Recurso não encontrado na Veracode (HTTP 404)'),
    'rate_limited': (502, 'Limite de requisições da Veracode excedido (HTTP 429) após as tentativas configuradas'),
    'upstream_error': (502, 'Erro no servidor da Veracode (HTTP 5xx) após as tentativas configuradas'),
    'bad_request': (502, 'Veracode rejeitou a requisição (HTTP 4xx)'),
    'timeout': (504, 'Tempo esgotado ao consultar a Veracode após as tentativas configuradas'),
    'network_error': (502, 'Falha de rede/TLS ao contatar a Veracode após as tentativas configuradas'),
    'invalid_response': (502, 'Resposta da Veracode em formato inesperado'),
    'request_budget_exhausted': (502, 'Orçamento de requisições da coleta esgotado'),
    'deadline_exceeded': (504, 'Prazo total da coleta excedido'),
    'inconsistent_pagination': (502, 'Paginação inconsistente (dados mudaram durante a coleta ou total divergente)'),
    'membership_count_mismatch': (502, 'Quantidade de membros do Team diverge do total informado pela Veracode'),
    # F05 — Reporting API
    'reporting_disabled': (409, 'Geração de relatórios da Reporting API desabilitada (AFRIKA_VERACODE_REPORTING_'
                                'ENABLED)'),
    'report_failed': (502, 'A Veracode informou falha no processamento do relatório (status FAILED)'),
    'report_poll_limit': (504, 'Relatório não concluiu dentro do limite de consultas de status'),
    'report_too_large': (502, 'Relatório com mais páginas que o limite configurado: resultado incompleto'),
}


class VeracodeError(Exception):
    def __init__(self, code: str, *, upstream_status: int | None = None):
        if code not in CATALOG:
            raise ValueError(f'código desconhecido: {code}')
        super().__init__(code)
        self.code = code
        self.upstream_status = upstream_status

    @property
    def http_status(self) -> int:
        return CATALOG[self.code][0]

    @property
    def message(self) -> str:
        return CATALOG[self.code][1]

    def as_dict(self) -> dict:
        return {'code': self.code, 'message': self.message, 'upstream_status': self.upstream_status}

    def __repr__(self) -> str:
        return f'VeracodeError({self.code!r}, upstream_status={self.upstream_status!r})'
