"""Integração Veracode SOMENTE LEITURA (F02): autenticação HMAC, cliente HTTP, adaptadores e descoberta.

Módulos:
- settings:     limites configuráveis por ambiente (timeouts, retries, concorrência, orçamento, cache).
- credentials:  resolução de `env:NOME` -> NOME_API_ID / NOME_API_KEY (valores nunca expostos).
- hmac_auth:    assinatura VERACODE-HMAC-SHA-256.
- http:         cliente compartilhado (GET apenas), paginação, retry/backoff/429, coleta completa/incompleta.
- adapters:     endpoints oficiais e normalização dos campos usados.
- cache:        cache TTL em memória isolado por escopo + conexão + credencial.
- discovery:    orquestra escopo (cliente/subcliente) -> conexão efetiva -> coletas.
- fixtures:     tenant Veracode SINTÉTICO (modo fixture, testes e E2E). Nunca dados reais.
"""
