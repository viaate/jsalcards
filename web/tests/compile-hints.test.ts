import { describe, expect, it } from 'vitest';

import { COMPILE_HINT, hintChunks } from '../tools/compile-hints';

describe('the chunks compiled whole as they download', () => {
  it('carry the hint on their first line, above what Vite put there, their maps a line down', () => {
    const bundle = {
      'assets/index-a1.js': {
        type: 'chunk' as const,
        fileName: 'assets/index-a1.js',
        name: 'index',
        code: 'const __vite__mapDeps=[];\nvar e=1;\n//# sourceMappingURL=index-a1.js.map',
      },
      'assets/index-a1.js.map': {
        type: 'asset' as const,
        fileName: 'assets/index-a1.js.map',
        source: JSON.stringify({ version: 3, mappings: ';AAAA' }),
      },
      'assets/maplibre-b2.js': {
        type: 'chunk' as const,
        fileName: 'assets/maplibre-b2.js',
        name: 'maplibre',
        code: 'import{a}from"./x.js";',
        map: { mappings: 'AAAA' },
      },
      'assets/glow-mount-c3.js': {
        type: 'chunk' as const,
        fileName: 'assets/glow-mount-c3.js',
        name: 'glow-mount',
        code: 'var g=1;',
      },
    };
    hintChunks(bundle, new Set(['index', 'maplibre']));
    hintChunks(bundle, new Set(['index', 'maplibre']));
    expect(bundle['assets/index-a1.js'].code.split('\n')[0]).toBe(COMPILE_HINT);
    expect(bundle['assets/index-a1.js'].code.split('\n')[1]).toBe('const __vite__mapDeps=[];');
    expect(JSON.parse(bundle['assets/index-a1.js.map'].source)).toEqual({
      version: 3,
      mappings: ';;AAAA',
    });
    expect(bundle['assets/maplibre-b2.js'].code).toBe(`${COMPILE_HINT}\nimport{a}from"./x.js";`);
    expect(bundle['assets/maplibre-b2.js'].map.mappings).toBe(';AAAA');
    // Chunks the page runs later keep compiling a function at a time.
    expect(bundle['assets/glow-mount-c3.js'].code).toBe('var g=1;');
  });
});
