/**
 * Source and layer ids of the basemap style (style.ts), in a module of their
 * own so code that only places layers, or reads what the map drew, can name
 * them without the style's dependencies.
 */

/** Source and layer ids other map code can place layers relative to. */
export const BASEMAP_IDS = {
  usSource: 'us-lines',
  /** The city and state names of the national view, from the same file, in a source of their own (style.ts). */
  usCitySource: 'us-cities',
  openFreeMapSource: 'openfreemap',
  background: 'background',
  /** The continental US and DC, a step off the ground, below the handover to street tiles. */
  usLand: 'us-land',
  usStates: 'us-states',
  /** The land's edge: coasts, lake shores and the borders with Canada and Mexico. */
  usOutline: 'us-outline',
  /** The national view's own state lines and outline, simplified (style.ts SIMPLE_LINES_UNTIL). */
  usStatesSimple: 'us-states-simple',
  usOutlineSimple: 'us-outline-simple',
  ofmPark: 'ofm-park',
  /** School grounds from OpenStreetMap: the campus around each school, a step off the ground. */
  ofmSchoolGrounds: 'ofm-school-grounds',
  /** Their hairline edge, up close. */
  ofmSchoolGroundsEdge: 'ofm-school-grounds-edge',
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
  ofmWaterLabel: 'ofm-label-water',
  ofmStreetLabel: 'ofm-label-street',
  ofmParkLabel: 'ofm-label-park',
  ofmMajorRoadLabel: 'ofm-label-major-road',
  ofmVillageLabel: 'ofm-label-village',
  ofmTownLabel: 'ofm-label-town',
  ofmCityLabel: 'ofm-label-city',
  /** City names of the national view, under the glow, up to the street tiles' names at zoom 7. */
  usCityLabel: 'us-label-city',
  /** State names on a phone, over the city names, the ones that fit at the map's zoom (style.ts). */
  usStateLabel: 'us-label-state',
  /**
   * The states in view on a phone closer in, named where their part in view
   * has room (state-areas.ts): a source the map fills as it comes to rest, and
   * its layer, over every place name.
   */
  usStateAreaSource: 'us-states-in-view',
  usStateAreaLabel: 'us-states-in-view-label',
  /**
   * The first street-tile label layer. Marks drawn under every label from
   * zoom 7, taking no part in label collisions, go before it: they sit above
   * the US mask, and above the national city names, which give way to these
   * labels at zoom 7.
   */
  labels: 'ofm-label-neighbourhood',
  /**
   * Where the glow layer (glow-mount.ts) goes: right over this empty layer,
   * which is right before `labels`. It is then over the ground, the lines,
   * the national names and the school dots, and under every label from zoom
   * 7, whatever order the other layers go on the map in (index.ts).
   */
  glowSlot: 'glow-slot',
  /** The glow layer. */
  glow: 'snowlight-glow',
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
  /** The space each dot keeps up close, unseen, placed before every label. */
  schoolSpace: 'school-space',
} as const;

/** The layer of schools.pmtiles (pipeline/snowlight/directory/tiles.py). */
export const SCHOOLS_TILE_LAYER = 'schools';

/**
 * The scheme of the school tiles' URLs, which MapLibre's workers serve from
 * the archive (school-tiles.ts): "snowlight-schools://<archive URL>/{z}/{x}/{y}".
 */
export const SCHOOL_TILES_PROTOCOL = 'snowlight-schools';
