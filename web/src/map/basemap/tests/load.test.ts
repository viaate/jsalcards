import { afterEach, describe, expect, it } from 'vitest';

import MAPLIBRE_URL from 'virtual:snowlight/maplibre-url';

import { preloadModule } from '../load';

afterEach(() => {
  for (const link of document.head.querySelectorAll('link[rel="modulepreload"]')) link.remove();
});

describe('asking for a module ahead of running it', () => {
  it('adds one module preload for it, however often it is asked for', () => {
    preloadModule('https://snow.test/assets/maplibre-AbCd1234.js');
    preloadModule('https://snow.test/assets/maplibre-AbCd1234.js');
    const links = [...document.head.querySelectorAll('link[rel="modulepreload"]')];
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      'https://snow.test/assets/maplibre-AbCd1234.js',
    ]);
  });

  it('knows where MapLibre’s page module is served', () => {
    expect(new URL(MAPLIBRE_URL).pathname).toMatch(/\/src\/map\/basemap\/maplibre\.ts$/);
  });
});
