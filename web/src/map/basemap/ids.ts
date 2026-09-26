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
  ofmCountries: 'ofm-country-lines',
  ofmRoadTunnel: 'ofm-road-tunnel',
  ofmBuilding: 'ofm-building',
  ofmRoad: 'ofm-road',
  ofmBridgeCasing: 'ofm-bridge-casing',
  ofmBridge: 'ofm-bridge',
  ofmNeighbourhoodLabel: 'ofm-label-neighbourhood',
  ofmStreetLabel: 'ofm-label-street',
  ofmMajorRoadLabel: 'ofm-label-major-road',
  ofmVillageLabel: 'ofm-label-village',
  ofmTownLabel: 'ofm-label-town',
  ofmCityLabel: 'ofm-label-city',
  /**
   * The first label layer. Marks drawn under every label, taking no part in
   * label collisions, go before it.
   */
  labels: 'ofm-label-neighbourhood',
  /**
   * Where the school layers go: add them before this empty layer, the last in
   * the style. They then sit above every street and place label, and MapLibre
   * places labels from the top layer down, so school names win collisions.
   */
  schools: 'schools-slot',
} as const;
