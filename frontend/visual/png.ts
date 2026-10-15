// F06B.1 — codec PNG mínimo (sem dependências): decodifica para RGBA 8 bits e codifica RGBA 8 bits.
// Suporta o que capturas do Chromium e exportações comuns (PowerPoint/LibreOffice) produzem: profundidade 8 (e 16,
// reduzida para 8), tipos de cor 0 (cinza), 2 (RGB), 3 (paleta 1/2/4/8 bits), 4 (cinza+alfa) e 6 (RGBA), sem
// entrelaçamento. Entrelaçado (Adam7) é recusado com mensagem clara — reexporte sem entrelaçamento.
import { deflateSync, inflateSync } from 'node:zlib';

export type Image = { width: number; height: number; data: Uint8Array }; // RGBA, linha a linha

const SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10];
export const MAX_PIXELS = 40_000_000; // limite defensivo contra arquivos malformados/gigantes

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(bytes: Uint8Array): number {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

export class PngError extends Error {}

export function decodePng(input: Uint8Array): Image {
  const buf = input instanceof Uint8Array ? input : new Uint8Array(input);
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  if (buf.length < 8 || SIGNATURE.some((b, i) => buf[i] !== b)) throw new PngError('arquivo não é PNG');
  let pos = 8;
  let width = 0, height = 0, depth = 0, colorType = -1, interlace = 0;
  let palette: Uint8Array | null = null;
  let trns: Uint8Array | null = null;
  const idat: Uint8Array[] = [];
  while (pos + 8 <= buf.length) {
    const len = dv.getUint32(pos);
    const type = String.fromCharCode(buf[pos + 4], buf[pos + 5], buf[pos + 6], buf[pos + 7]);
    const start = pos + 8;
    if (start + len + 4 > buf.length) throw new PngError(`chunk ${type} truncado`);
    const body = buf.subarray(start, start + len);
    if (type === 'IHDR') {
      width = dv.getUint32(start);
      height = dv.getUint32(start + 4);
      depth = buf[start + 8];
      colorType = buf[start + 9];
      interlace = buf[start + 12];
    } else if (type === 'PLTE') palette = body;
    else if (type === 'tRNS') trns = body;
    else if (type === 'IDAT') idat.push(body);
    else if (type === 'IEND') break;
    pos = start + len + 4;
  }
  if (!width || !height) throw new PngError('IHDR ausente');
  if (width * height > MAX_PIXELS) throw new PngError(`imagem grande demais (${width}×${height})`);
  if (interlace !== 0) throw new PngError('PNG entrelaçado (Adam7) não suportado: reexporte sem entrelaçamento');
  const channels = ({ 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 } as Record<number, number>)[colorType];
  if (!channels) throw new PngError(`tipo de cor ${colorType} não suportado`);
  if (colorType === 3 ? ![1, 2, 4, 8].includes(depth) : ![8, 16].includes(depth))
    throw new PngError(`profundidade ${depth} não suportada para tipo de cor ${colorType}`);
  if (colorType === 3 && !palette) throw new PngError('PNG de paleta sem PLTE');

  const bitsPerPixel = channels * depth;
  const bpp = Math.max(1, bitsPerPixel >> 3); // bytes por pixel para os filtros
  const stride = Math.ceil((width * bitsPerPixel) / 8);
  const raw = inflateSync(concat(idat));
  if (raw.length < (stride + 1) * height) throw new PngError('dados de imagem truncados');
  const lines = new Uint8Array(stride * height);
  let prev = new Uint8Array(stride);
  for (let y = 0; y < height; y++) {
    const f = raw[y * (stride + 1)];
    const src = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    const out = lines.subarray(y * stride, (y + 1) * stride);
    for (let i = 0; i < stride; i++) {
      const a = i >= bpp ? out[i - bpp] : 0;
      const b = prev[i];
      const c = i >= bpp ? prev[i - bpp] : 0;
      let v: number;
      if (f === 0) v = src[i];
      else if (f === 1) v = src[i] + a;
      else if (f === 2) v = src[i] + b;
      else if (f === 3) v = src[i] + ((a + b) >> 1);
      else if (f === 4) {
        const p = a + b - c;
        const pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
        v = src[i] + (pa <= pb && pa <= pc ? a : pb <= pc ? b : c);
      } else throw new PngError(`filtro ${f} inválido`);
      out[i] = v & 0xff;
    }
    prev = out;
  }

  const data = new Uint8Array(width * height * 4);
  const sample = (row: number, idx: number): number => {
    // amostra `idx` (em unidades de amostra) da linha; 16 bits => byte mais significativo
    if (depth === 16) return lines[row * stride + idx * 2];
    if (depth === 8) return lines[row * stride + idx];
    const perByte = 8 / depth;
    const byte = lines[row * stride + Math.floor(idx / perByte)];
    const shift = 8 - depth * ((idx % perByte) + 1);
    return (byte >> shift) & ((1 << depth) - 1);
  };
  const scale = depth < 8 && colorType === 0 ? 255 / ((1 << depth) - 1) : 1;
  for (let y = 0; y < height; y++)
    for (let x = 0; x < width; x++) {
      const o = (y * width + x) * 4;
      if (colorType === 3) {
        const i = sample(y, x);
        data[o] = palette![i * 3];
        data[o + 1] = palette![i * 3 + 1];
        data[o + 2] = palette![i * 3 + 2];
        data[o + 3] = trns && i < trns.length ? trns[i] : 255;
      } else if (colorType === 0 || colorType === 4) {
        const g = sample(y, x * channels) * scale;
        data[o] = data[o + 1] = data[o + 2] = g;
        data[o + 3] = colorType === 4 ? sample(y, x * 2 + 1) : 255;
      } else {
        data[o] = sample(y, x * channels);
        data[o + 1] = sample(y, x * channels + 1);
        data[o + 2] = sample(y, x * channels + 2);
        data[o + 3] = colorType === 6 ? sample(y, x * 4 + 3) : 255;
      }
    }
  return { width, height, data };
}

function concat(parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) {
    out.set(p, o);
    o += p.length;
  }
  return out;
}

function chunk(type: string, body: Uint8Array): Uint8Array {
  const out = new Uint8Array(12 + body.length);
  const dv = new DataView(out.buffer);
  dv.setUint32(0, body.length);
  for (let i = 0; i < 4; i++) out[4 + i] = type.charCodeAt(i);
  out.set(body, 8);
  dv.setUint32(8 + body.length, crc32(out.subarray(4, 8 + body.length)));
  return out;
}

/** RGBA 8 bits, filtro "Sub" por linha (bom para áreas chapadas). Determinístico. */
export function encodePng(img: Image): Uint8Array {
  const { width, height, data } = img;
  const stride = width * 4;
  const raw = new Uint8Array((stride + 1) * height);
  for (let y = 0; y < height; y++) {
    const o = y * (stride + 1);
    raw[o] = 1;
    for (let i = 0; i < stride; i++) {
      const v = data[y * stride + i];
      raw[o + 1 + i] = (v - (i >= 4 ? data[y * stride + i - 4] : 0)) & 0xff;
    }
  }
  const ihdr = new Uint8Array(13);
  const dv = new DataView(ihdr.buffer);
  dv.setUint32(0, width);
  dv.setUint32(4, height);
  ihdr.set([8, 6, 0, 0, 0], 8);
  return concat([
    new Uint8Array(SIGNATURE),
    chunk('IHDR', ihdr),
    chunk('IDAT', new Uint8Array(deflateSync(raw, { level: 9 }))),
    chunk('IEND', new Uint8Array(0)),
  ]);
}

/** Monta um PNG arbitrário a partir de linhas JÁ no formato do tipo de cor (testes do decodificador). */
export function buildPng(o: { width: number; height: number; colorType: number; depth: number; lines: Uint8Array; palette?: Uint8Array; trns?: Uint8Array; filter?: number }): Uint8Array {
  const stride = o.lines.length / o.height;
  const raw = new Uint8Array((stride + 1) * o.height);
  for (let y = 0; y < o.height; y++) {
    raw[y * (stride + 1)] = o.filter ?? 0;
    const line = o.lines.subarray(y * stride, (y + 1) * stride);
    const prev = y ? o.lines.subarray((y - 1) * stride, y * stride) : new Uint8Array(stride);
    for (let i = 0; i < stride; i++) raw[y * (stride + 1) + 1 + i] = (line[i] - (o.filter === 2 ? prev[i] : 0)) & 0xff;
  }
  const ihdr = new Uint8Array(13);
  const dv = new DataView(ihdr.buffer);
  dv.setUint32(0, o.width);
  dv.setUint32(4, o.height);
  ihdr.set([o.depth, o.colorType, 0, 0, 0], 8);
  return concat([
    new Uint8Array(SIGNATURE),
    chunk('IHDR', ihdr),
    ...(o.palette ? [chunk('PLTE', o.palette)] : []),
    ...(o.trns ? [chunk('tRNS', o.trns)] : []),
    chunk('IDAT', new Uint8Array(deflateSync(raw))),
    chunk('IEND', new Uint8Array(0)),
  ]);
}

export function blankImage(width: number, height: number, rgba: [number, number, number, number] = [255, 255, 255, 255]): Image {
  const data = new Uint8Array(width * height * 4);
  for (let i = 0; i < data.length; i += 4) data.set(rgba, i);
  return { width, height, data };
}
