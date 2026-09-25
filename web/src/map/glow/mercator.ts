/**
 * Web Mercator math in MapLibre's convention: x and y run 0..1 across the
 * world, (0, 0) is the north-west corner at longitude -180 and the maximum
 * Mercator latitude, and y grows southward.
 */

/** Latitude at which Web Mercator is clipped, in degrees. */
export const MAX_MERCATOR_LATITUDE = 85.051129;

export function mercatorXFromLng(lng: number): number {
  return (180 + lng) / 360;
}

export function mercatorYFromLat(lat: number): number {
  const clamped = Math.min(Math.max(lat, -MAX_MERCATOR_LATITUDE), MAX_MERCATOR_LATITUDE);
  const phi = (clamped * Math.PI) / 180;
  return (180 - (180 / Math.PI) * Math.log(Math.tan(Math.PI / 4 + phi / 2))) / 360;
}

export function lngFromMercatorX(x: number): number {
  return x * 360 - 180;
}

export function latFromMercatorY(y: number): number {
  const y2 = 180 - y * 360;
  return (360 / Math.PI) * Math.atan(Math.exp((y2 * Math.PI) / 180)) - 90;
}

/**
 * Splits a double into a float32 `hi` part and a float32 `lo` remainder so
 * that `hi + lo` carries about 48 bits of the original. The shader subtracts
 * a float32 origin from `hi` first, which is exact near the camera, then adds
 * `lo`. That keeps points steady at street zoom where a single float32 would
 * snap in whole-pixel steps while panning.
 */
export function splitDouble(value: number): [hi: number, lo: number] {
  const hi = Math.fround(value);
  return [hi, Math.fround(value - hi)];
}

/**
 * Pixel size of the whole world at a zoom level, for MapLibre's 512 px tiles.
 * Used to convert between mercator units and CSS pixels.
 */
export function worldSizePx(zoom: number): number {
  return 512 * 2 ** zoom;
}
