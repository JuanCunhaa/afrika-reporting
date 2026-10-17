import type { Plugin } from 'vite';
export declare const STAMP_INPUTS: string[];
export declare function sourceHash(): { hash: string; files: number };
export declare function renderStamp(): Plugin;
