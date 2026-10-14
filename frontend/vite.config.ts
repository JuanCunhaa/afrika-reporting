import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// AFRIKA_API_URL permite apontar o proxy para outra porta (ex.: backend isolado do E2E).
export default defineConfig(({ mode }) => {
  const apiTarget = loadEnv(mode, '.', 'AFRIKA_').AFRIKA_API_URL || 'http://localhost:8000';
  return { plugins: [react()], server: { proxy: { '/api': apiTarget } } };
});
