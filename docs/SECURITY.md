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
- **Logs SQL em DEBUG (F01.1)**: em DEBUG o SQLAlchemy logaria **linhas de resultado** (nomes de clientes). `app.db.DropSqlResultRows` é instalado no logger `sqlalchemy.engine.Engine` a cada `make_engine` e descarta todo registro DEBUG desse logger; o filtro fica no logger (não no handler) e sobrevive a `dictConfig`/`uvicorn --log-config`. SQL em INFO continua visível, com parâmetros ocultos. Testado in-process e com servidor real + `--log-config` acidental, com controle negativo (sem o filtro os testes falham).
- **Banco**: `data/*.sqlite3` e `frontend/.e2e-data/` estão no `.gitignore`. Testes e E2E usam bancos temporários com dados sintéticos.
- **`.env.example`**: `scripts/check_env_example.py` classifica cada variável (vazio/placeholder/valor padrão não secreto/REVISAR) **sem imprimir valores** e recusa ler `.env` real. Roda no CI quando o arquivo está versionado.
- **Dependências Python**: versões exatas em `backend/constraints.txt` (aplicado por `requirements.txt`); CI roda `pip check`.
- **Publicação pública do código (2026-10-14)**: autorizada pelo titular após licença integral (PolyForm Noncommercial 1.0.0 + `NOTICE`), declaração de titularidade e auditoria (gitleaks histórico + árvore, sem dados reais). Isso **não** autoriza expor a aplicação: a API continua sem autenticação e só para uso local.

## Controles implementados na F02 (integração Veracode somente leitura)

- **Loopback obrigatório** (`app/local_only.py`): requisições com IP de origem não-loopback ou `Host` fora de
  localhost/127.0.0.1/::1 recebem 403 (protege contra `--host 0.0.0.0` acidental e DNS rebinding). Não substitui autenticação.
- **Credenciais**: só do ambiente do backend (`env:NOME` → `NOME_API_ID`/`NOME_API_KEY`), lidas por requisição, nunca persistidas,
  nunca devolvidas (nem valores, nem nomes derivados), `repr` mascarado. A UI recebe apenas o estado (`configured`/`missing`/…).
- **Somente leitura**: hook do cliente HTTP bloqueia qualquer método ≠ GET antes do envio; hosts fixos por região; redirects e `_links` não seguidos (sem SSRF); TLS sempre validado; cookies desativados (cliente compartilhado entre tenants sem estado).
- **Logs**: só recurso, status, tentativa, espera e IDs internos (UUID). `httpx`/`httpcore` filtrados para WARNING+ (não logam URL com query). Testes com controle negativo.
- **Minimização**: e-mail/telefone/IP de usuários descartados na normalização; nada coletado vai para disco; cache só em memória com chave sem credenciais.
- **Fixtures**: tenant sintético gerado em código (`app/veracode/fixtures.py`); credenciais sintéticas derivadas de rótulos fixos — não são chaves reais.
- **Integração real**: somente opt-in (`backend/tests_live`, `AFRIKA_VERACODE_LIVE=1`) com autorização do operador; nunca no CI.
