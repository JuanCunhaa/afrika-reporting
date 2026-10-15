import { createHash } from 'node:crypto';

// Credenciais SINTÉTICAS dos tenants fixture, derivadas como em backend/app/veracode/fixtures.py
// (synthetic_credentials). Não são chaves Veracode reais; só autenticam no tenant fixture em processo.
export const fixtureCreds = (tenant: string) => ({
  id: createHash('sha256').update(`afrika-fixture:${tenant}:id`).digest('hex').slice(0, 32),
  key: createHash('sha512').update(`afrika-fixture:${tenant}:key`).digest('hex'),
});

const alpha = fixtureCreds('alpha');
const denied = fixtureCreds('denied');

// Ambiente do backend E2E: modo fixture + referências usadas pelo seed e pelos testes.
export const veracodeFixtureEnv = {
  AFRIKA_VERACODE_MODE: 'fixture',
  AFRIKA_DOTENV_DISABLED: '1', // F02.1: o .env local (credenciais de teste) nunca entra no backend E2E
  AFRIKA_DEMO_VERACODE_API_ID: alpha.id, // seed: env:AFRIKA_DEMO_VERACODE
  AFRIKA_DEMO_VERACODE_API_KEY: alpha.key,
  AFRIKA_E2E_DENIED_API_ID: denied.id, // tenant sem permissão na Identity API (403)
  AFRIKA_E2E_DENIED_API_KEY: denied.key,
  // F05: Reporting API habilitada SOMENTE contra o tenant fixture (sintético, em processo); polling curto.
  AFRIKA_VERACODE_REPORTING_ENABLED: 'true',
  AFRIKA_VERACODE_REPORTING_POLL_INTERVAL: '0.2',
  AFRIKA_VERACODE_REPORTING_POLL_MAX_INTERVAL: '0.5',
};

export const SYNTHETIC_SECRET_VALUES = [alpha.id, alpha.key, denied.id, denied.key];
export const SYNTHETIC_SECRET_NAMES = Object.keys(veracodeFixtureEnv).filter((k) => k.endsWith('_API_ID') || k.endsWith('_API_KEY'));
