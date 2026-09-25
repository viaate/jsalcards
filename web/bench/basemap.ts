/**
 * The bench's basemap: black, with the bundled continental US outline and
 * state lines from us-atlas (Census cartographic boundaries). No network
 * requests: the TopoJSON is bundled into the bench page.
 */
import type { MultiLineString, MultiPolygon, Polygon } from 'geojson';
import type { StyleSpecification } from 'maplibre-gl';
import { feature, merge, mesh, type TopoGeometry, type Topology } from 'topojson-client';
import atlas from 'us-atlas/counties-10m.json';

/** FIPS codes outside the continental US: Alaska, Hawaii and the territories. */
const NON_CONUS = new Set(['02', '15', '60', '66', '69', '72', '78']);

/** State FIPS is the whole id for a state and the first two digits for a county. */
const isConus = (geometry: TopoGeometry): boolean =>
  geometry.id !== undefined && !NON_CONUS.has(String(geometry.id).slice(0, 2));

export interface ConusGeometry {
  readonly outline: MultiLineString;
  readonly stateLines: MultiLineString;
  readonly land: MultiPolygon;
  /** Every continental county as a polygon (multi-part counties split), for synthetic sampling. */
  readonly counties: readonly Polygon[];
}

export function conusGeometry(): ConusGeometry {
  const topology = atlas as unknown as Topology;
  const states = topology.objects.states;
  const counties = topology.objects.counties;
  if (states === undefined || counties === undefined) {
    throw new Error('bench: us-atlas is missing states or counties');
  }
  const countyPolygons: Polygon[] = [];
  for (const county of feature(topology, {
    type: 'GeometryCollection',
    geometries: counties.geometries.filter(isConus),
  }).features) {
    const geometry = county.geometry;
    if (geometry.type === 'Polygon') countyPolygons.push(geometry);
    if (geometry.type === 'MultiPolygon') {
      for (const coordinates of geometry.coordinates)
        countyPolygons.push({ type: 'Polygon', coordinates });
    }
  }
  return {
    counties: countyPolygons,
    outline: mesh(topology, states, (a, b) => a === b && isConus(a)),
    stateLines: mesh(topology, states, (a, b) => a !== b && isConus(a) && isConus(b)),
    land: merge(topology, states.geometries.filter(isConus)),
  };
}

export function benchStyle(geometry: ConusGeometry): StyleSpecification {
  return {
    version: 8,
    sources: {
      outline: { type: 'geojson', data: geometry.outline },
      states: { type: 'geojson', data: geometry.stateLines },
    },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': '#000000' } },
      {
        id: 'state-lines',
        type: 'line',
        source: 'states',
        paint: { 'line-color': '#ffffff', 'line-opacity': 0.1, 'line-width': 0.5 },
      },
      {
        id: 'outline',
        type: 'line',
        source: 'outline',
        paint: { 'line-color': '#ffffff', 'line-opacity': 0.32, 'line-width': 0.7 },
      },
    ],
  };
}
