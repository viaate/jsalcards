/**
 * The mask for one street tile, from the archive: the tile's own mask tile
 * if the archive has it, else its nearest ancestor's, scaled up and cut to
 * the tile. A tile with no stored ancestor at all is outside the US.
 */
import { BORDER_LAYER, MASK_BOX, MASK_LAYER, MASK_MIN_ZOOM } from './format';
import { clipLine, clipRing, ringArea } from './geometry';
import { EXTENT, LINE, POLYGON, decodeTile } from './mvt';
import type { ArchiveReader } from './pmtiles';

export interface TileMask {
  readonly kind: 'inside' | 'outside' | 'mixed';
  /** Rings whose inside (even-odd) is outside the US, in tile units within MASK_BOX. */
  readonly rings: readonly number[][];
  /** The border with Canada and Mexico, in tile units within MASK_BOX. */
  readonly border: readonly number[][];
}

const BOX_AREA = (MASK_BOX.hi - MASK_BOX.lo) ** 2;

export const OUTSIDE: TileMask = { kind: 'outside', rings: [], border: [] };

/**
 * A mask tile's shape in the frame of a tile `levels` zooms below it, at
 * `dx`, `dy` among its descendants at that zoom.
 */
export function maskFromTile(bytes: Uint8Array, levels = 0, dx = 0, dy = 0): TileMask {
  const scale = 2 ** levels;
  const move = (part: readonly number[]): number[] =>
    part.map((value, i) => value * scale - (i % 2 === 0 ? dx : dy) * EXTENT);
  const rings: number[][] = [];
  const border: number[][] = [];
  for (const layer of decodeTile(bytes)) {
    if (layer.extent !== EXTENT)
      throw new Error(`mask: layer ${layer.name} is not ${String(EXTENT)} units`);
    for (const feature of layer.features) {
      if (layer.name === MASK_LAYER && feature.type === POLYGON) {
        for (const part of feature.parts()) {
          const ring = clipRing(move(part), MASK_BOX);
          if (ring.length > 0) rings.push(ring);
        }
      } else if (layer.name === BORDER_LAYER && feature.type === LINE) {
        for (const part of feature.parts()) border.push(...clipLine(move(part), MASK_BOX));
      }
    }
  }
  const area = rings.reduce((sum, ring) => sum + ringArea(ring), 0);
  if (area <= BOX_AREA * 1e-9) return { kind: 'inside', rings: [], border: [] };
  if (area >= BOX_AREA * (1 - 1e-9)) return { kind: 'outside', rings: [], border: [] };
  return { kind: 'mixed', rings, border };
}

/** The mask for street tile z/x/y. */
export async function tileMask(
  reader: ArchiveReader,
  z: number,
  x: number,
  y: number,
): Promise<TileMask> {
  const { header } = await reader.start();
  for (let zoom = Math.min(z, header.maxZoom); zoom >= MASK_MIN_ZOOM; zoom--) {
    const levels = z - zoom;
    const ax = Math.floor(x / 2 ** levels);
    const ay = Math.floor(y / 2 ** levels);
    const bytes = await reader.tile(zoom, ax, ay);
    if (bytes === null) continue;
    return maskFromTile(bytes, levels, x - ax * 2 ** levels, y - ay * 2 ** levels);
  }
  return OUTSIDE;
}
