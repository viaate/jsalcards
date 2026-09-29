/**
 * A street tile cut to the US: what OpenFreeMap sent, with every name, road,
 * river and line outside the US taken out, and the mask and the border line
 * added as layers of their own (format.ts).
 *
 * - Points (every name, and anything else drawn at a point) outside the US are
 *   dropped, so they are neither drawn nor placed: a name in Windsor never
 *   pushes a name in Detroit aside.
 * - Lines (roads, street names, rivers, boundaries) are cut where they cross
 *   the border, and only their US parts kept; one whose US part rounds down
 *   to a single point is dropped, as nothing of it could be drawn.
 * - Areas (water, parks, buildings) wholly outside the US are dropped; those
 *   the border crosses stay whole, and the mask, drawn over them, hides
 *   their part outside.
 * - The border line is drawn on land, lakes and rivers, and stops at the
 *   coast, as the sea boundaries were never drawn.
 *
 * No feature goes out without geometry (mvt.ts encodeGeometry): MapLibre's
 * worker fails a tile holding one, and the tile is never drawn.
 */
import { BORDER_LAYER, MASK_BOX, MASK_LAYER } from './format';
import { MaskIndex, clipRing } from './geometry';
import {
  EXTENT,
  LINE,
  POINT,
  POLYGON,
  decodeTile,
  encodeTile,
  newLayer,
  stringProperty,
} from './mvt';
import type { Feature, LayerOutput, Parts } from './mvt';
import type { TileMask } from './source';

/** OpenMapTiles water polygons of this class are the sea. */
const WATER_LAYER = 'water';
const SEA_CLASS = 'ocean';

function bounds(parts: Parts): [number, number, number, number] {
  let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const part of parts) {
    for (let i = 0; i + 1 < part.length; i += 2) {
      const x = part[i] ?? 0;
      const y = part[i + 1] ?? 0;
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
    }
  }
  return [x0, y0, x1, y1];
}

/** Whether a line came back from the mask exactly as it went in: not cut anywhere. */
function same(a: readonly number[], b: readonly number[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

function rounded(part: readonly number[]): number[] {
  return part.map(Math.round);
}

/** The feature as it goes out: unchanged (its raw bytes), with new geometry, or null to drop it. */
function maskFeature(feature: Feature, index: MaskIndex): Uint8Array | null {
  if (feature.type !== POINT && feature.type !== LINE && feature.type !== POLYGON) return null;
  const parts = feature.parts();
  if (parts.length === 0) return null;
  const [x0, y0, x1, y1] = bounds(parts);
  if (index.clear(x0, y0, x1, y1)) return feature.raw;
  if (feature.type === POLYGON) return index.covers(x0, y0, x1, y1) ? null : feature.raw;
  if (feature.type === POINT) {
    const kept = parts.filter((part) => !index.contains(part[0] ?? 0, part[1] ?? 0));
    if (kept.length === parts.length) return feature.raw;
    return kept.length === 0 ? null : feature.withParts(kept);
  }
  let changed = false;
  const kept: Parts = [];
  for (const part of parts) {
    const pieces = index.unmaskedParts(part);
    const [only] = pieces;
    if (pieces.length === 1 && only !== undefined && same(only, part)) {
      kept.push(part);
    } else {
      changed = true;
      kept.push(...pieces.map(rounded));
    }
  }
  if (!changed) return feature.raw;
  // Pieces a few centimetres long round to a single point: with only those left, it is dropped.
  return kept.length === 0 ? null : feature.withParts(kept);
}

/** The border line, less its parts out at sea. */
function borderOffshore(border: readonly number[][], sea: readonly number[][]): number[][] {
  if (sea.length === 0) return border.map(rounded);
  const index = new MaskIndex(sea, MASK_BOX);
  return border.flatMap((line) => index.unmaskedParts(line)).map(rounded);
}

/**
 * The street tile cut to the US by `mask`. A tile wholly inside comes back as
 * it is, one wholly outside as an empty tile.
 */
export function maskStreetTile(tile: Uint8Array, mask: TileMask): Uint8Array {
  if (mask.kind === 'inside') return tile;
  if (mask.kind === 'outside') return new Uint8Array(0);
  const index = new MaskIndex(mask.rings, MASK_BOX);
  const out: LayerOutput[] = [];
  const sea: number[][] = [];
  for (const layer of decodeTile(tile)) {
    if (layer.extent !== EXTENT) continue;
    const features: Uint8Array[] = [];
    for (const feature of layer.features) {
      const kept = maskFeature(feature, index);
      if (kept !== null) features.push(kept);
      if (
        layer.name === WATER_LAYER &&
        feature.type === POLYGON &&
        stringProperty(layer, feature, 'class') === SEA_CLASS
      ) {
        for (const ring of feature.parts()) {
          const clipped = clipRing(ring, MASK_BOX);
          if (clipped.length > 0) sea.push(clipped);
        }
      }
    }
    if (features.length > 0) out.push({ fields: layer.fields, features });
  }
  out.push(newLayer(MASK_LAYER, [{ type: POLYGON, parts: mask.rings.map(rounded) }]));
  const border = borderOffshore(mask.border, sea);
  out.push(newLayer(BORDER_LAYER, [{ type: LINE, parts: border }]));
  return encodeTile(out);
}
