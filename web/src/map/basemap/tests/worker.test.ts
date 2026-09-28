/**
 * MapLibre's worker as the page starts it: its one import of the shared
 * module pointed at the page's chunk, and the street tile protocol, which
 * cuts street tiles to the US, registered in it once MapLibre's worker has
 * set up its scope.
 */
import { describe, expect, it } from 'vitest';

import rawSource from 'maplibre-gl/dist/maplibre-gl-worker.mjs?raw';

import { workerSource } from '../maplibre-worker';

const URLS = {
  shared: 'https://snowlight.test/assets/maplibre-shared-abc.js',
  streetTiles: 'https://snowlight.test/assets/street-tiles-def.js',
  schoolTiles: 'https://snowlight.test/assets/school-tiles-ghi.js',
  mask: 'https://snowlight.test/geo/us-mask.0123456789.pmtiles',
};

describe('the MapLibre worker source', () => {
  const source = workerSource(URLS);

  it('imports the shared module from the page chunk, once', () => {
    expect(source).not.toContain('./maplibre-gl-shared.mjs');
    expect(source.split(JSON.stringify(URLS.shared))).toHaveLength(2);
    expect(source).not.toMatch(/sourceMappingURL/);
  });

  it('keeps GeoJSON read from a URL in the worker: nothing goes back for the page to copy in', () => {
    // MapLibre's own source hands it back once, in its GeoJSON worker source's loadData.
    expect(rawSource.match(/\b(\w+)\.request&&\((\w+)\.data=\1\.data\)/g)).toHaveLength(1);
    expect(source).not.toMatch(/\b(\w+)\.request&&\((\w+)\.data=\1\.data\)/);
    expect(source).toMatch(
      /clearLoaded\(\);let (\w+)=\{\};return !1,this\._finishRequestTiming\(\w+,\w+,\1\),\1\}/,
    );
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

  it('registers the school tile protocol after MapLibre sets up the worker', () => {
    const setUp = source.indexOf('self.worker=new');
    const register = source.indexOf('snowlightRegisterSchoolTiles(self);');
    expect(register).toBeGreaterThan(setUp);
    expect(source).toContain(
      `import { registerSchoolTiles as snowlightRegisterSchoolTiles } from ${JSON.stringify(URLS.schoolTiles)};`,
    );
  });
});
