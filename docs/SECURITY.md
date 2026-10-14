# Regras mínimas de segurança

- Git público somente com código autoral e fixtures sintéticas.
- Nunca versionar PPTX real de cliente, export CSV/JSONL de findings, .env, credentials, banco SQLite, relatórios gerados ou dados de pessoas.
- Credenciais HMAC exclusivamente no backend (variáveis ambiente / store seguro). Não armazenar segredos em SQLite plaintext.
- Mascarar tokens, headers Authorization, IDs/chaves em logs, trace e handoff.
- Backend Veracode read-only; TLS validado, sem `verify=False`.
- Restringir CORS em produção; demo local aceita localhost somente.
- Fluxos com acesso real só após autorização expressa e teste de permissões.
- Revisar dependências, proteção de branches, scanner de secrets, licenças de terceiros antes de tornar repo público.

## Controles implementados na F01

- **API sem autenticação**: uso exclusivamente local (`127.0.0.1`). **Não expor publicamente** nem em rede compartilhada até existir autenticação/autorização (fase futura, não decidida).
- **Conexões**: o banco guarda só metadados e `credential_ref` no formato `env:NOME` (nome de variável de ambiente do backend). Valores com aparência de chave (sequência hexadecimal ≥ 24) são recusados. Não há campo para API ID/Key; campos desconhecidos geram 422 (`extra='forbid'`).
- **Erros**: formato único `{"error": {code, message, details}}`; o `input` do Pydantic é descartado, então valores enviados não são ecoados. Erro 500 retorna mensagem genérica e loga só o tipo da exceção.
- **Logs**: a aplicação loga apenas IDs (UUID), nunca nomes ou payloads. Engine com `hide_parameters=True` (parâmetros SQL ocultos em logs e exceções).
- **Atenção**: com `sqlalchemy.engine` em nível DEBUG, o SQLAlchemy loga **linhas de resultado** (nomes de clientes). O padrão é WARNING; não habilite DEBUG desse logger com dados reais.
- **Banco**: `data/*.sqlite3` e `frontend/.e2e-data/` estão no `.gitignore`. Testes e E2E usam bancos temporários com dados sintéticos.
