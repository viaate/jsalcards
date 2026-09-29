/**
 * Street tiles cut to the US, served inside MapLibre's workers.
 *
 * maplibre-worker.ts imports this module into each worker and calls
 * registerStreetTiles there, so the style's `openfreemap://` tiles load in the
 * worker that parses them: the US mask tile for the same place is read
 * (mask/source.ts), a tile wholly outside the US is answered with an empty
 * tile without asking OpenFreeMap for it, one wholly inside is passed through
 * untouched, and one the border crosses is cut (mask/rewrite.ts). Nothing
 * outside the US reaches MapLibre, so nothing there is drawn, placed or
 * queryable. The page registers no handler of its own for the scheme: if the
 * workers could not cut tiles, the map would show no streets rather than
 * streets past the border.
 *
 * The mask is a small archive (under 1 MB), fetched whole, once, by the page
 * and sent to each worker (mask/feed.ts): never read in byte ranges, which a
 * server or cache can answer from a compressed copy of the file. A tile
 * wholly inside the US (us-inside.ts, most of them) needs no mask, and is
 * asked for at once; any other is asked of OpenFreeMap only once the mask is
 * in: it could not be drawn before, and it may not need asking for at all.
 *
 * The page imports this module too, only for its URL (the chunk the workers
 * import), as it does maplibre-shared.ts. It must not touch the DOM.
 */
import type { AddProtocolAction } from 'maplibre-gl';

import { pageMaskSource, ownMaskSource } from './mask/feed';
import type { MaskSource } from './mask/feed';
import { ArchiveReader } from './mask/pmtiles';
import { maskStreetTile } from './mask/rewrite';
import { tileMask } from './mask/source';
import { OPENFREEMAP_PROTOCOL, loadOpenFreeMapTile } from './openfreemap';
import { insideUs } from './us-inside';

/** URL of this module's chunk, which each worker imports. */
export const STREET_TILES_URL: string = import.meta.url;

/** What a worker offers: MapLibre's worker sets addProtocol on its global scope. */
export interface WorkerScope {
  addProtocol?: (name: string, action: AddProtocolAction) => void;
}

const TILE_PATH = /\/(\d+)\/(\d+)\/(\d+)$/;

/** The reason MapLibre gave for no longer wanting a tile, as an error to throw. */
function aborted(signal: AbortSignal): Error {
  const reason: unknown = signal.reason;
  return reason instanceof Error ? reason : new DOMException('Aborted', 'AbortError');
}

/**
 * The protocol handler: street tile z/x/y, cut to the US by `mask` (the mask
 * the page sends, or one at a URL, fetched by this worker itself). A tile
 * wholly inside the US (`inside`) is asked of OpenFreeMap at once; any other
 * only once the mask is in, and only when some of it is in the US.
 */
export function streetTileLoader(
  mask: MaskSource | string,
  loadTile: typeof loadOpenFreeMapTile = loadOpenFreeMapTile,
  archive?: ArchiveReader,
  inside: (z: number, x: number, y: number) => boolean = insideUs,
): AddProtocolAction {
  const source = typeof mask === 'string' ? ownMaskSource(mask) : mask;
  const reader = archive ?? new ArchiveReader(source.reader);
  return async (request, abortController) => {
    const match = TILE_PATH.exec(request.url);
    if (match === null) throw new Error(`Street tiles: unexpected request ${request.url}`);
    const [z, x, y] = match.slice(1).map(Number) as [number, number, number];
    const { signal } = abortController;
    if (inside(z, x, y)) return loadTile(request.url, signal);
    source.nudge();
    const cutBy = await tileMask(reader, z, x, y);
    if (signal.aborted) throw aborted(signal);
    if (cutBy.kind === 'outside') return { data: new ArrayBuffer(0) };
    const tile = await loadTile(request.url, signal);
    if (cutBy.kind === 'inside') return tile;
    const cut = maskStreetTile(new Uint8Array(tile.data), cutBy);
    return { ...tile, data: cut.buffer.slice(cut.byteOffset, cut.byteOffset + cut.byteLength) };
  };
}

/**
 * Serves the style's street tiles in this worker, cut by the mask at
 * `maskUrl`: sent by the page on its `channel` (mask/feed.ts), or, with no
 * channel, fetched by the worker itself.
 */
export function registerStreetTiles(scope: WorkerScope, maskUrl: string, channel?: string): void {
  if (scope.addProtocol === undefined) throw new Error('Street tiles: not in a MapLibre worker');
  const mask = channel === undefined ? maskUrl : pageMaskSource(maskUrl, channel);
  scope.addProtocol(OPENFREEMAP_PROTOCOL, streetTileLoader(mask));
}
