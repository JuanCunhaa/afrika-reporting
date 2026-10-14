import { defineConfig } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { veracodeFixtureEnv } from './e2e/fixture-creds';

// E2E F01: sobe API (FastAPI) + Vite em portas próprias, com banco SQLite NOVO por execução
// (migrate + seed sintético). Nunca reaproveita servidores de dev nem toca no banco local do usuário.
// PW_CHANNEL=msedge|chrome usa navegador instalado; vazio => Chromium do Playwright (padrão do CI).
// PYTHON aponta para o interpretador com backend/requirements instalado (padrão: python).
const here = path.dirname(fileURLToPath(import.meta.url));
const backendDir = path.resolve(here, '../backend');
// Caminho (contém separador) => absoluto, pois o webServer roda com cwd=backend; nome simples => PATH.
const pythonEnv = process.env.PYTHON || 'python';
const python = /[\\/]/.test(pythonEnv) ? path.resolve(pythonEnv) : pythonEnv;
const API_PORT = 8010;
const UI_PORT = 5183;

// Definido uma vez no processo principal; workers herdam o mesmo valor pelo ambiente.
process.env.AFRIKA_E2E_DB ??= path.join(here, '.e2e-data', `e2e-${Date.now()}.sqlite3`);
const dbUrl = `sqlite:///${process.env.AFRIKA_E2E_DB.replace(/\\/g, '/')}`;

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 0,
  workers: 1, // um único banco compartilhado entre specs; execução serial e determinística
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${UI_PORT}`,
    channel: process.env.PW_CHANNEL || undefined,
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `"${python}" -m app.cli migrate && "${python}" -m app.cli seed-demo && "${python}" -m uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: backendDir,
      // F02: Veracode em modo FIXTURE (tenant sintético em processo). Nenhuma chamada à Veracode real.
      env: {
        ...process.env,
        ...veracodeFixtureEnv,
        AFRIKA_DATABASE_URL: dbUrl,
        CORS_ORIGINS: `http://127.0.0.1:${UI_PORT}`,
      } as Record<string, string>,
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 90_000,
    },
    {
      command: `npm run dev -- --port ${UI_PORT} --strictPort`,
      cwd: here,
      env: { ...process.env, AFRIKA_API_URL: `http://127.0.0.1:${API_PORT}` } as Record<string, string>,
      url: `http://127.0.0.1:${UI_PORT}`,
      reuseExistingServer: false,
      timeout: 90_000,
    },
  ],
});
