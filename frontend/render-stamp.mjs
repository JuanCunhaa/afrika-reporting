// F07 — carimbo do renderizador: o build grava em `dist/afrika-render.json` o hash do código-fonte que gerou o bundle.
// O backend recalcula o mesmo hash (`backend/app/export/renderer.py`) e RECUSA exportar com um `dist` diferente do
// código atual, para o PPTX/PDF saírem do mesmo renderizador da pré-visualização. Regra (igual nos dois lados): arquivos
// das entradas abaixo, caminhos relativos POSIX em ordem, SHA-256 de `caminho\0sha256(conteúdo)\n`.
// (JavaScript puro: usa APIs do Node fora do projeto TypeScript do app, que não tem tipos do Node.)
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
export const STAMP_INPUTS = ['src', 'index.html', 'package-lock.json', 'vite.config.ts', 'tsconfig.json'];

export function sourceHash() {
  const files = [];
  const walk = (rel) => {
    const abs = path.join(here, rel);
    if (fs.statSync(abs).isDirectory()) for (const name of fs.readdirSync(abs)) walk(path.posix.join(rel, name));
    else files.push(rel);
  };
  for (const input of STAMP_INPUTS) if (fs.existsSync(path.join(here, input))) walk(input);
  files.sort();
  const h = createHash('sha256');
  for (const f of files) h.update(`${f}\0${createHash('sha256').update(fs.readFileSync(path.join(here, f))).digest('hex')}\n`);
  return { hash: h.digest('hex'), files: files.length };
}

export function renderStamp() {
  return {
    name: 'afrika-render-stamp',
    apply: 'build',
    generateBundle() {
      const { hash, files } = sourceHash();
      this.emitFile({ type: 'asset', fileName: 'afrika-render.json', source: `${JSON.stringify({ stamp_version: 1, source_hash: hash, files, inputs: STAMP_INPUTS }, null, 2)}\n` });
    },
  };
}
