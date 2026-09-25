/**
 * MapLibre's shared module ships without type declarations. Only
 * maplibre-shared.ts re-exports it, for MapLibre's worker; nothing in this
 * code base reads its exports.
 */
declare module 'maplibre-gl/dist/maplibre-gl-shared.mjs';
