// Minimal types for the parts of topojson-client the bench uses.
declare module 'topojson-client' {
  import type {
    FeatureCollection,
    GeoJsonProperties,
    MultiLineString,
    MultiPolygon,
    Polygon,
  } from 'geojson';

  export interface TopoGeometry {
    readonly type: string;
    readonly id?: string | number;
    readonly properties?: GeoJsonProperties;
  }

  export interface TopoCollection {
    readonly type: 'GeometryCollection';
    readonly geometries: TopoGeometry[];
  }

  export interface Topology {
    readonly type: 'Topology';
    readonly objects: Readonly<Partial<Record<string, TopoCollection>>>;
  }

  export function mesh(
    topology: Topology,
    object?: TopoCollection,
    filter?: (a: TopoGeometry, b: TopoGeometry) => boolean,
  ): MultiLineString;

  export function feature(
    topology: Topology,
    object: TopoCollection,
  ): FeatureCollection<Polygon | MultiPolygon>;

  export function merge(topology: Topology, objects: TopoGeometry[]): MultiPolygon;
}
