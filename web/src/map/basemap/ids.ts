/**
 * Source and layer ids of the basemap style (style.ts), in a module of their
 * own so code that only places layers, or reads what the map drew, can name
 * them without the style's dependencies.
 */

/** Source and layer ids other map code can place layers relative to. */
export const BASEMAP_IDS = {
  usSource: 'us-lines',
  openFreeMapSource: 'openfreemap',
  background: 'background',
  usStates: 'us-states',
  usOutline: 'us-outline',
  ofmPark: 'ofm-park',
  ofmWaterFill: 'ofm-water-fill',
  ofmWaterway: 'ofm-waterway',
  ofmStates: 'ofm-state-lines',
  ofmWater: 'ofm-water-edge',
  ofmRoadTunnel: 'ofm-road-tunnel',
  ofmBuilding: 'ofm-building',
  ofmRoad: 'ofm-road',
  ofmBridgeCasing: 'ofm-bridge-casing',
  ofmBridge: 'ofm-bridge',
  /**
   * The ground drawn over everything outside the continental US and DC, from
   * zoom 7 (mask/format.ts). Every street, water, park and building layer is
   * under it; the border line, the bundled US lines, every label and the
   * school layers are over it. Street tiles are cut to the US before they are
   * drawn (street-tiles.ts), so nothing outside it is placed or queryable
   * either; the mask hides the parts of areas the border crosses.
   */
  usMask: 'us-mask',
  /** The border with Canada and Mexico on land, lakes and rivers, along the mask's edge. */
  usBorder: 'us-border',
  ofmNeighbourhoodLabel: 'ofm-label-neighbourhood',
  ofmStreetLabel: 'ofm-label-street',
  ofmMajorRoadLabel: 'ofm-label-major-road',
  ofmVillageLabel: 'ofm-label-village',
  ofmTownLabel: 'ofm-label-town',
  ofmCityLabel: 'ofm-label-city',
  /**
   * The first label layer. Marks drawn under every label, taking no part in
   * label collisions, go before it: they sit above the US mask.
   */
  labels: 'ofm-label-neighbourhood',
  /**
   * Where the school layers go: add them before this empty layer, the last in
   * the style. They then sit above the US mask and every street and place
   * label, and MapLibre places labels from the top layer down, so school
   * names win collisions.
   */
  schools: 'schools-slot',
  /** Every school in the directory (schools.pmtiles), when the build ships it. */
  schoolsSource: 'schools',
  /** A dot at each school, under the glow and every label. */
  schoolDots: 'school-dots',
  /** Each school's name, over every other label. */
  schoolNames: 'school-names',
} as const;

/** The layer of schools.pmtiles (pipeline/snowlight/directory/tiles.py). */
export const SCHOOLS_TILE_LAYER = 'schools';

/**
 * The scheme of the school tiles' URLs, which MapLibre's workers serve from
 * the archive (school-tiles.ts): "snowlight-schools://<archive URL>/{z}/{x}/{y}".
 */
export const SCHOOL_TILES_PROTOCOL = 'snowlight-schools';
