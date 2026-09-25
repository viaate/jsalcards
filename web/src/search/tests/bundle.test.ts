// @vitest-environment node
import { mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { gzipSync } from 'node:zlib';

import { build } from 'vite';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

/**
 * Builds the search client with the app's own Vite config, as the site will
 * ship it, and checks what comes out.
 */
const web = resolve(import.meta.dirname, '../../..');
const outDir = mkdtempSync(join(tmpdir(), 'snowlight-search-bundle-'));
let files: { name: string; text: string; gzip: number }[] = [];

beforeAll(async () => {
  await build({
    configFile: join(web, 'vite.config.ts'),
    root: web,
    logLevel: 'silent',
    build: {
      outDir,
      emptyOutDir: true,
      sourcemap: false,
      copyPublicDir: false,
      rollupOptions: {
        input: join(web, 'src/search/index.ts'),
        preserveEntrySignatures: 'strict',
      },
    },
  });
  const walk = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
      e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)],
    );
  files = walk(outDir)
    .filter((f) => f.endsWith('.js'))
    .map((f) => {
      const text = readFileSync(f, 'utf8');
      return { name: f.slice(outDir.length + 1), text, gzip: gzipSync(text).length };
    });
}, 120_000);

afterAll(() => {
  rmSync(outDir, { recursive: true, force: true });
});

describe('search bundle', () => {
  it('runs the engine in its own worker chunk', () => {
    // The index magic number is read by the engine only.
    const magic = /1230195795|0x49534c53/i;
    const worker = files.filter((f) => f.name.includes('worker'));
    expect(worker).toHaveLength(1);
    expect(worker[0]?.text).toMatch(magic);
    for (const f of files.filter((g) => !g.name.includes('worker'))) {
      expect(f.text, f.name).not.toMatch(magic);
    }
  });

  it('keeps the page-side client small', () => {
    const client = files.filter((f) => !f.name.includes('worker'));
    expect(client.length).toBeGreaterThan(0);
    const clientGzip = client.reduce((sum, f) => sum + f.gzip, 0);
    const workerGzip = files.find((f) => f.name.includes('worker'))?.gzip ?? 0;
    process.stdout.write(
      `search client ${String(clientGzip)} B gzip, worker ${String(workerGzip)} B gzip\n`,
    );
    expect(clientGzip).toBeLessThan(3_000);
    expect(workerGzip).toBeLessThan(20_000);
  });

  it('ships nothing synthetic', () => {
    for (const f of files) {
      expect(f.text, f.name).not.toMatch(/synthetic|mulberry|SYN[A-Z]?\d/i);
    }
  });
});
