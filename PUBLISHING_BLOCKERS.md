# Antes de publicar no GitHub

1. Substituir o arquivo LICENSE provisório pelo texto **integral e inalterado** do PolyForm Noncommercial 1.0.0: https://github.com/polyformproject/polyform-licenses/blob/1.0.0/PolyForm-Noncommercial-1.0.0.md. **(fechado 2026-10-14)** — `LICENSE` = texto oficial da tag `1.0.0` (git blob `5ecc88c`, idêntico ao upstream); `NOTICE` com `Required Notice`.
2. Confirmar titularidade e autorização de comercialização do código, marca e materiais produzidos em contexto corporativo. **(fechado 2026-10-14 por declaração do titular)** — o usuário declarou ser o autor e titular pessoal do código e do nome; não é validação jurídica independente.
3. Verificar secrets, bibliotecas, licença de dependências e nenhum arquivo real de cliente. (2026-10-14: gitleaks em todo o histórico e na árvore HEAD — sem achados; dependências não são vendorizadas.)
4. Não incluir PPTX/PDF de clientes reais no repo público, nem citar nomes de clientes reais em arquivos versionados.
5. ~~Rodar npm install / npm run build localmente~~ — verificado em F00 (Windows 11, Node 24, npm 12).
6. Após `git init`/primeiro push: ativar branch protection, secret scanning/push protection e Dependabot; confirmar CI verde no GitHub (workflow ainda não executado em runner real).
