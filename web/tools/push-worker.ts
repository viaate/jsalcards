/**
 * The notifications' part of the service worker (src/pwa/push.ts, docs/notify.md),
 * bundled from src/pwa/push-worker.ts into one classic script with nothing outside
 * it, and written as PUSH_FILE beside the generated worker, which imports it
 * (src/pwa/config.ts workboxOptions). The words come with it (src/copy-notify.ts):
 * a notification shows in the site's own words, made when it shows.
 */

import path from 'node:path';

import { build } from 'vite';
import type { Plugin } from 'vite';

import { PUSH_FILE } from '../src/pwa/config.ts';

export const PUSH_ENTRY = 'src/pwa/push-worker.ts';

/** The worker script: src/pwa/push-worker.ts and what it imports, as one minified IIFE. */
export async function pushScript(root: string): Promise<string> {
  const result = await build({
    configFile: false,
    root,
    logLevel: 'silent',
    publicDir: false,
    build: {
      write: false,
      emptyOutDir: false,
      minify: true,
      sourcemap: false,
      target: 'es2022',
      lib: { entry: path.join(root, PUSH_ENTRY), formats: ['iife'], name: 'snowlightPush' },
    },
  });
  const outputs = (Array.isArray(result) ? result : [result]) as { output?: unknown[] }[];
  for (const out of outputs) {
    for (const item of out.output ?? []) {
      const chunk = item as { type?: string; code?: string };
      if (chunk.type === 'chunk' && typeof chunk.code === 'string') return chunk.code;
    }
  }
  throw new Error(`push worker: bundling ${PUSH_ENTRY} gave no script`);
}

/** The plugin: writes PUSH_FILE in a build. */
export function pushWorker(root: string): Plugin {
  return {
    name: 'snowlight:push-worker',
    apply: 'build',
    async generateBundle() {
      this.emitFile({ type: 'asset', fileName: PUSH_FILE, source: await pushScript(root) });
    },
  };
}
