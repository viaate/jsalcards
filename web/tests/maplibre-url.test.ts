import path from 'node:path';

import { describe, expect, it } from 'vitest';

import { MAPLIBRE_URL_MODULE, maplibreUrl } from '../tools/maplibre-url';

type Hook = (...args: unknown[]) => unknown;

/** The plugin as the bundler drives it: resolved config, then its hooks by name. */
function plugin(command: 'build' | 'serve', root = '/site') {
  const made = maplibreUrl();
  const hook = (name: keyof typeof made): Hook => {
    const value = made[name] as unknown;
    if (typeof value !== 'function') throw new Error(`no ${name} hook`);
    return (...args) => (value as Hook).apply({}, args);
  };
  hook('configResolved')({ root, command });
  const id = hook('resolveId')(MAPLIBRE_URL_MODULE);
  return { id: id as string, load: hook('load'), renderChunk: hook('renderChunk') };
}

const PAGE = path.join('/site', 'src/map/basemap/maplibre.ts');

describe('the URL of MapLibre’s page module', () => {
  it('is the chunk built from it, relative to the chunk asking, as the bundler names it', () => {
    const { id, load, renderChunk } = plugin('build');
    const code = load(id) as string;
    const rendered = renderChunk(
      `const a = 1;\n${code}`,
      { fileName: 'assets/index-!~{001}~.js' },
      {},
      {
        chunks: {
          'assets/index-!~{001}~.js': { fileName: 'assets/index-!~{001}~.js' },
          'assets/maplibre-!~{002}~.js': {
            fileName: 'assets/maplibre-!~{002}~.js',
            facadeModuleId: PAGE,
          },
        },
      },
    ) as { code: string };
    expect(rendered.code).toContain('const chunk = "./maplibre-!~{002}~.js";');
    expect(rendered.code).not.toContain('__SNOWLIGHT');
  });

  it('leaves every other chunk as it is, and fails a build with no chunk of it', () => {
    const { id, load, renderChunk } = plugin('build');
    expect(renderChunk('const a = 1;', { fileName: 'assets/a.js' }, {}, { chunks: {} })).toBe(null);
    expect(() =>
      renderChunk(load(id), { fileName: 'assets/index.js' }, {}, { chunks: {} }),
    ).toThrow(/no chunk is built from src\/map\/basemap\/maplibre\.ts/);
  });

  it('is the source file’s own path on the dev server', () => {
    const { id, load } = plugin('serve');
    expect(load(id)).toContain('"src/map/basemap/maplibre.ts"');
    expect(load('something else')).toBe(null);
  });
});
