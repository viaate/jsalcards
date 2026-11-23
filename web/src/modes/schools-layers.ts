/**
 * Hides Schools' map layers while another mode shows, and shows them again when Schools comes
 * back (flights spec D2): the glow, the school dots and their names, and the later rings. The
 * basemap (land, lines, city names) is every mode's and stays.
 *
 * The later rings are hidden by their own module too, while new rings are on their way
 * (map/later-rings.ts), so coming back never shows them: the host sends MODE_EVENT and the rings'
 * module puts them back as its own state says, and keeps them hidden while another mode shows.
 */
import type { Basemap } from '../map/basemap';
import { BASEMAP_IDS } from '../map/basemap/ids';

/**
 * The later rings' layers (map/later-rings.ts LATER_RING_LAYERS, which a test holds this to),
 * named here so this chunk never pulls the rings' code in.
 */
export const RING_LAYER_IDS = ['later-rings', 'later-rings-near', 'later-rings-close'] as const;

/** Sent on the window each time the mode shown changes (map/later-rings.ts listens). */
export const MODE_EVENT = 'snowlight:mode';

const RINGS: ReadonlySet<string> = new Set(RING_LAYER_IDS);

/** Schools' own layers by id; any layer on the school tiles' source is Schools' too. */
export const SCHOOL_LAYER_IDS: ReadonlySet<string> = new Set([
  BASEMAP_IDS.glow,
  BASEMAP_IDS.schoolDots,
  BASEMAP_IDS.schoolLight,
  BASEMAP_IDS.schoolSelected,
  BASEMAP_IDS.schoolNames,
  BASEMAP_IDS.schoolSpace,
  ...RING_LAYER_IDS,
]);

interface LayerLike {
  readonly id: string;
  readonly source?: unknown;
}

/** Whether a style layer is Schools' own. */
export function isSchoolLayer(layer: LayerLike): boolean {
  return SCHOOL_LAYER_IDS.has(layer.id) || layer.source === BASEMAP_IDS.schoolsSource;
}

export function showSchoolLayers(basemap: Pick<Basemap, 'map'>, shown: boolean): void {
  const { map } = basemap;
  // The layers by id, the glow among them: a custom layer is in the map's order, never in the
  // style getStyle() writes out. Before its style is in, the map has no layers to hide: its
  // styledata event comes again.
  let layers: readonly LayerLike[];
  try {
    layers = map.getLayersOrder().map((id) => ({ id, source: map.getLayer(id)?.source }));
  } catch {
    layers = [];
  }
  const visibility = shown ? 'visible' : 'none';
  for (const layer of layers) {
    if (!isSchoolLayer(layer)) continue;
    // Shown again only by the rings' own module, which knows whether their data is in.
    if (shown && RINGS.has(layer.id)) continue;
    try {
      if (map.getLayoutProperty(layer.id, 'visibility') !== visibility)
        map.setLayoutProperty(layer.id, 'visibility', visibility);
    } catch {
      // A layer that went with a style change: the next style's are set as it comes in.
    }
  }
}
