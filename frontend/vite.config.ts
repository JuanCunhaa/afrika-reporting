import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { renderStamp } from './render-stamp.mjs';

// AFRIKA_API_URL permite apontar o proxy para outra porta (ex.: backend isolado do E2E).
// F07: `renderStamp` grava o hash do código-fonte do renderizador no build (ver render-stamp.mjs).
export default defineConfig(({ mode }) => {
  const apiTarget = loadEnv(mode, '.', 'AFRIKA_').AFRIKA_API_URL || 'http://localhost:8000';
  return { plugins: [react(), renderStamp()], server: { proxy: { '/api': apiTarget } } };
});
