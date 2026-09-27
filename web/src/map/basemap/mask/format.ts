/**
 * What the US mask archive holds and how street tiles carry it. Shared by the
 * build script (scripts/build-us-mask.mjs), the street tile workers and the
 * map style.
 *
 * Each mask tile is a vector tile with one polygon in MASK_LAYER, the part of
 * the tile and its buffer outside the continental US and DC, and in
 * BORDER_LAYER the land and inland-water border with Canada and Mexico, drawn
 * along the same edges. A tile wholly inside the US has an empty MASK_LAYER, one
 * wholly outside a polygon covering it all. The archive holds every tile that
 * is not wholly outside at MASK_MIN_ZOOM, and every child of a tile the border
 * or the coast crosses, down to the zoom that tile needs; any other tile takes
 * its nearest stored ancestor's shape.
 *
 * Street tiles that the border crosses carry both layers too, cut to the
 * tile, so the style draws the mask and the border line from them.
 */
import type { Box } from './geometry';
import { EXTENT } from './mvt';

/** The polygon outside the US. */
export const MASK_LAYER = 'us_mask';
/** The border with Canada and Mexico, on land and inland water. */
export const BORDER_LAYER = 'us_border';

/** The first zoom the mask is stored at: where street tiles start. */
export const MASK_MIN_ZOOM = 7;

/**
 * Tile units the mask reaches past each edge of a tile, in both the archive
 * and the street tiles: 16 px at 512 px tiles, further than any line drawn
 * or queried in a tile reaches out of it.
 */
export const MASK_BUFFER = 128;

/** A tile and its buffer, in tile units. */
export const MASK_BOX: Box = { lo: -MASK_BUFFER, hi: EXTENT + MASK_BUFFER };
