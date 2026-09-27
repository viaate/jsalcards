/**
 * MapLibre's worker as the page starts it: its one import of the shared
 * module pointed at the page's chunk, and the street tile protocol, which
 * cuts street tiles to the US, registered in it once MapLibre's worker has
 * set up its scope.
 */
import { describe, expect, it } from 'vitest';

import { workerSource } from '../maplibre-worker';

const URLS = {
  shared: 'https://snowlight.test/assets/maplibre-shared-abc.js',
  streetTiles: 'https://snowlight.test/assets/street-tiles-def.js',
  mask: 'https://snowlight.test/geo/us-mask.0123456789.pmtiles',
};

describe('the MapLibre worker source', () => {
  const source = workerSource(URLS);

  it('imports the shared module from the page chunk, once', () => {
    expect(source).not.toContain('./maplibre-gl-shared.mjs');
    expect(source.split(JSON.stringify(URLS.shared))).toHaveLength(2);
    expect(source).not.toMatch(/sourceMappingURL/);
  });

  it('registers the street tile protocol after MapLibre sets up the worker', () => {
    const setUp = source.indexOf('self.worker=new');
    const register = source.indexOf(
      `snowlightRegisterStreetTiles(self, ${JSON.stringify(URLS.mask)})`,
    );
    expect(setUp).toBeGreaterThan(0);
    expect(register).toBeGreaterThan(setUp);
    expect(source).toContain(
      `import { registerStreetTiles as snowlightRegisterStreetTiles } from ${JSON.stringify(URLS.streetTiles)};`,
    );
  });
});
