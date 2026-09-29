/**
 * Street tiles cut to the US, served inside MapLibre's workers.
 *
 * maplibre-worker.ts imports this module into each worker and calls
 * registerStreetTiles there, so the style's `openfreemap://` tiles load in the
 * worker that parses them: the US mask tile for the same place is read
 * (mask/source.ts), a tile wholly outside the US is answered with an empty
 * tile without asking OpenFreeMap for it once the mask is in, one wholly
 * inside is passed through untouched, and one the border crosses is cut
 * (mask/rewrite.ts). Nothing
 * outside the US reaches MapLibre, so nothing there is drawn, placed or
 * queryable. The page registers no handler of its own for the scheme: if the
 * workers could not cut tiles, the map would show no streets rather than
 * streets past the border.
 *
 * The mask is a small archive (under 1 MB), fetched whole by each worker when
 * its first street tile is asked for, and kept (mask/pmtiles.ts
 * wholeFileReader): never read in byte ranges, which a server or cache can
 * answer from a compressed copy of the file. Until it is in, each tile is
 * asked of OpenFreeMap alongside it, so the first street tiles come no later
 * for it.
 *
 * The page imports this module too, only for its URL (the chunk the workers
 * import), as it does maplibre-shared.ts. It must not touch the DOM.
 */
import type { AddProtocolAction } from 'maplibre-gl';

import { maskStreetTile } from './mask/rewrite';
import { tileMask } from './mask/source';
import { ArchiveReader, wholeFileReader } from './mask/pmtiles';
import { OPENFREEMAP_PROTOCOL, loadOpenFreeMapTile } from './openfreemap';

/** URL of this module's chunk, which each worker imports. */
export const STREET_TILES_URL: string = import.meta.url;

/** What a worker offers: MapLibre's worker sets addProtocol on its global scope. */
export interface WorkerScope {
  addProtocol?: (name: string, action: AddProtocolAction) => void;
}

const TILE_PATH = /\/(\d+)\/(\d+)\/(\d+)$/;

/** The protocol handler: street tile z/x/y, cut to the US by the mask at `maskUrl`. */
export function streetTileLoader(
  maskUrl: string,
  loadTile: typeof loadOpenFreeMapTile = loadOpenFreeMapTile,
  archive: ArchiveReader = new ArchiveReader(wholeFileReader(maskUrl)),
): AddProtocolAction {
  /** Whether the mask is in: from then on a tile outside the US is never asked for. */
  let maskIn = false;
  return async (request, abortController) => {
    const match = TILE_PATH.exec(request.url);
    if (match === null) throw new Error(`Street tiles: unexpected request ${request.url}`);
    const [z, x, y] = match.slice(1).map(Number) as [number, number, number];
    // Until the mask is in, the tile is asked for alongside it, and dropped if it is outside the US.
    const own = new AbortController();
    const abort = (): void => {
      own.abort(abortController.signal.reason);
    };
    abortController.signal.addEventListener('abort', abort, { once: true });
    try {
      const early = maskIn ? null : loadTile(request.url, own.signal);
      early?.catch(() => undefined);
      const mask = await tileMask(archive, z, x, y);
      maskIn = true;
      if (mask.kind === 'outside') {
        own.abort();
        return { data: new ArrayBuffer(0) };
      }
      const tile = await (early ?? loadTile(request.url, own.signal));
      if (mask.kind === 'inside') return tile;
      const cut = maskStreetTile(new Uint8Array(tile.data), mask);
      return { ...tile, data: cut.buffer.slice(cut.byteOffset, cut.byteOffset + cut.byteLength) };
    } finally {
      abortController.signal.removeEventListener('abort', abort);
    }
  };
}

/** Serves the style's street tiles in this worker. */
export function registerStreetTiles(scope: WorkerScope, maskUrl: string): void {
  if (scope.addProtocol === undefined) throw new Error('Street tiles: not in a MapLibre worker');
  scope.addProtocol(OPENFREEMAP_PROTOCOL, streetTileLoader(maskUrl));
}
