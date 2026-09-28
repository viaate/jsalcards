/**
 * Has the browser compile the code the page runs as it starts whole, as it
 * downloads it, on the thread that reads it in, rather than a function at a
 * time on the page's main thread as each first runs.
 *
 * V8 (Chrome 126 and later) takes the hint from the comment
 * `//# allFunctionsCalledOnLoad` at the top of a script; elsewhere it is a
 * comment. The chunks named here get it: the shell, which runs as the page
 * starts, and the map's code and MapLibre's, which run all at once as the map
 * starts (creating the map alone first runs some 370 of MapLibre's
 * functions). It goes on as the build writes them, after anything else put at
 * their top (Vite's list of a chunk's dependencies), their source maps moved
 * down the line it takes.
 */
import type { Plugin } from 'vite';

export const COMPILE_HINT = '//# allFunctionsCalledOnLoad';

/** A chunk with its code and source map, or an asset (a chunk's source map file among them). */
interface Written {
  type: 'chunk' | 'asset';
  fileName: string;
  name?: string;
  code?: string;
  map?: { mappings: string } | null;
  source?: string | Uint8Array;
}

/**
 * Puts the hint at the top of each chunk of the build named in `names`, and
 * moves its source map down a line: the map file the build writes for it,
 * or, before there is one, the map it keeps with the chunk.
 */
export function hintChunks(bundle: Record<string, Written>, names: ReadonlySet<string>): void {
  for (const output of Object.values(bundle)) {
    if (output.type !== 'chunk' || output.code === undefined) continue;
    if (output.name === undefined || !names.has(output.name)) continue;
    if (output.code.startsWith(COMPILE_HINT)) continue;
    output.code = `${COMPILE_HINT}\n${output.code}`;
    const file = bundle[`${output.fileName}.map`];
    if (file?.type === 'asset' && file.source !== undefined) {
      const text =
        typeof file.source === 'string' ? file.source : new TextDecoder().decode(file.source);
      const map = JSON.parse(text) as { mappings: string };
      map.mappings = `;${map.mappings}`;
      file.source = JSON.stringify(map);
    } else if (output.map) {
      output.map.mappings = `;${output.map.mappings}`;
    }
  }
}

export function compileHints(names: ReadonlySet<string>): Plugin {
  return {
    name: 'snowlight:compile-hints',
    apply: 'build',
    generateBundle: {
      order: 'post',
      handler(_options, bundle) {
        hintChunks(bundle as unknown as Record<string, Written>, names);
      },
    },
  };
}
