"""F12 — diagnóstico REAL opt-in da PRÓPRIA conta autenticada (mesmo portão de test_veracode_live).

Exatamente UMA requisição: GET /api/authn/v2/users/self (autorizada pelo PO na F12). Nenhum POST (a Reporting API NÃO
é chamada), nenhuma consulta a outros usuários, nenhuma alteração de permissões.

Grava o resultado JÁ minimizado (`self_diagnostic.diagnose`: sem identificadores, e-mail, nomes, IPs nem Teams) em
`private/f12/` (ignorado pelo Git) e imprime só códigos de estado.

    python -m pytest tests_live/test_f12_self_diagnostic_live.py -q -s -rs --run-veracode-live   (a partir de backend/)
"""
import asyncio
import json
from dataclasses import replace
from pathlib import Path

from app.veracode import credentials, self_diagnostic
from app.veracode.http import CollectionRun, VeracodeHttpPool

from test_veracode_live import _settings

OUT_DIR = Path(__file__).resolve().parents[2] / 'private' / 'f12'


def test_live_own_account_permissions(veracode_live_gate):
    gate = veracode_live_gate
    creds = credentials.resolve(gate.credential_ref)
    settings = replace(_settings(), cache_ttl=0, max_retries=0)

    async def main():
        pool = VeracodeHttpPool(settings)
        try:
            run = CollectionRun(pool, creds, gate.region, max_requests=1)
            return await self_diagnostic.run_self_diagnostic(run)
        finally:
            await pool.aclose()

    out = asyncio.run(main())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / 'self_diagnostic.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    assert out['requests'] == 1
    if out['status'] != 'ok':
        print(f"\nF12 users/self: erro {out['error']['code']} (upstream {out['error'].get('upstream_status')})")
        return
    rep = out['reporting_api']
    print(f"\nF12 users/self: ok; conta={out['account']['account_type']}; papéis={len(out['roles'] or [])}; "
          f"reporting={rep['role_state']}; leitura403={out['reporting_403_reading']['cause']}; "
          f"credencial={out['credential']['expiration']}; team_restricted={out['account']['team_restricted']}")
    text = json.dumps(out)
    for forbidden in ('email', 'user_name', 'user_id', 'api_id', 'first_name', 'last_name', 'ip_address'):
        assert forbidden not in text
