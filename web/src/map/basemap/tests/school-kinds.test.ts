import { featureFilter } from '@maplibre/maplibre-gl-style-spec';
import type { FilterSpecification } from 'maplibre-gl';
import { describe, expect, it } from 'vitest';

import { SHOW_ALL, withKind } from '../../../state/filter';
import { BASEMAP_IDS } from '../ids';
import { SCHOOL_KIND_LAYERS, schoolKindFilter } from '../schools';

/** Whether a filter keeps a school tile's feature (pipeline/snowlight/directory/tiles.py). */
function keeps(filter: FilterSpecification | null, id: string, kind: number): boolean {
  if (filter === null) return true;
  return featureFilter(filter, 'filter').filter(
    { zoom: 13 },
    { type: 1, properties: { id, name: 'A school', kind } },
  );
}

const PUBLIC_SCHOOL = '291640000557';
const PRIVATE_SCHOOL = 'A1902690';

describe('the school dots and names of the kinds the menu shows', () => {
  it('are every school while it shows both kinds', () => {
    const filter = schoolKindFilter(SHOW_ALL, null);
    expect(filter).toBeNull();
    expect(schoolKindFilter(SHOW_ALL, PRIVATE_SCHOOL)).toBeNull();
    expect(keeps(filter, PUBLIC_SCHOOL, 0)).toBe(true);
    expect(keeps(filter, PRIVATE_SCHOOL, 1)).toBe(true);
  });

  it('tell a private school by its kind flags; charter and virtual schools are public', () => {
    const publicOnly = schoolKindFilter(withKind(SHOW_ALL, 'private', false), null);
    expect(keeps(publicOnly, PUBLIC_SCHOOL, 0)).toBe(true);
    expect(keeps(publicOnly, PUBLIC_SCHOOL, 2)).toBe(true);
    expect(keeps(publicOnly, PUBLIC_SCHOOL, 6)).toBe(true);
    expect(keeps(publicOnly, PRIVATE_SCHOOL, 1)).toBe(false);
    expect(keeps(publicOnly, PRIVATE_SCHOOL, 5)).toBe(false);
    const privateOnly = schoolKindFilter(withKind(SHOW_ALL, 'public', false), null);
    expect(keeps(privateOnly, PUBLIC_SCHOOL, 0)).toBe(false);
    expect(keeps(privateOnly, PRIVATE_SCHOOL, 1)).toBe(true);
    const neither = schoolKindFilter({ public: false, private: false }, null);
    expect(keeps(neither, PUBLIC_SCHOOL, 0)).toBe(false);
    expect(keeps(neither, PRIVATE_SCHOOL, 1)).toBe(false);
  });

  it('keep the school whose panel is open, whatever its kind', () => {
    const publicOnly = schoolKindFilter(withKind(SHOW_ALL, 'private', false), PRIVATE_SCHOOL);
    expect(keeps(publicOnly, PRIVATE_SCHOOL, 1)).toBe(true);
    expect(keeps(publicOnly, 'A0000001', 1)).toBe(false);
    const neither = schoolKindFilter({ public: false, private: false }, PUBLIC_SCHOOL);
    expect(keeps(neither, PUBLIC_SCHOOL, 0)).toBe(true);
    expect(keeps(neither, '291640000558', 0)).toBe(false);
  });

  it('apply to the dots, their light, the names and each dot’s space, not the open school’s ring', () => {
    expect(SCHOOL_KIND_LAYERS).toEqual([
      BASEMAP_IDS.schoolDots,
      BASEMAP_IDS.schoolLight,
      BASEMAP_IDS.schoolNames,
      BASEMAP_IDS.schoolSpace,
    ]);
    expect(SCHOOL_KIND_LAYERS).not.toContain(BASEMAP_IDS.schoolSelected);
  });
});
