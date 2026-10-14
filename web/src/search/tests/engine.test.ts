// @vitest-environment node
import { describe, expect, it } from 'vitest';

import { loadIndex } from '../decode';
import { encodeIndex } from '../encode';
import { DEFAULT_LIMIT, LEAD_FACTOR, START_FACTOR, SearchEngine, highlight } from '../engine';
import type { GroupName, SearchRecord, SearchResults } from '../types';
import { SYNTHETIC_RECORDS } from './synthetic-fixture';

const engine = new SearchEngine(loadIndex(encodeIndex(SYNTHETIC_RECORDS).bytes));

function ids(q: string, group: GroupName, limit?: number): string[] {
  return engine.search(q, limit)[group].map((h) => h.id);
}

function first(q: string, group: GroupName) {
  return engine.search(q)[group][0];
}

function total(r: SearchResults): number {
  return r.schools.length + r.cities.length + r.zips.length;
}

describe('matching', () => {
  it('ranks an exact name first, then heavier matches', () => {
    // Every city named exactly Lancaster, heaviest first; New Lancaster
    // matches a whole word too but is not the whole name.
    expect(ids('lancaster', 'cities')).toEqual(['SYNC02', 'SYNC01', 'SYNC04', 'SYNC03', 'SYNC05']);
  });

  describe('a name that starts with the words and is far heavier', () => {
    // Places as pipeline/out/site-data/search has them (September 2026): the four named Kansas,
    // the two Kansas Cities and North Kansas City; the three Portlands and South Portland.
    const place = (
      geoid: string,
      name: string,
      sub: string,
      state: string,
      weight: number,
      lat: number,
      lon: number,
    ): SearchRecord => ({ kind: 'city', id: geoid, name, sub, state, lat, lon, weight });
    const places = new SearchEngine(
      loadIndex(
        encodeIndex([
          place('0139280', 'Kansas', 'Alabama', 'AL', 185, 33.902808, -87.556598),
          place('1738986', 'Kansas', 'Illinois', 'IL', 647, 39.55446, -87.939554),
          place('3939578', 'Kansas', 'Ohio', 'OH', 0, 41.24515, -83.283916),
          place('4038600', 'Kansas', 'Oklahoma', 'OK', 756, 36.205359, -94.788945),
          place('2036000', 'Kansas City', 'Kansas', 'KS', 157805, 39.122539, -94.741781),
          place('2938000', 'Kansas City', 'Missouri', 'MO', 521220, 39.125155, -94.550313),
          place('2953102', 'North Kansas City', 'Missouri', 'MO', 5613, 39.139553, -94.565159),
          place('4159000', 'Portland', 'Oregon', 'OR', 635109, 45.536951, -122.649971),
          place('2360545', 'Portland', 'Maine', 'ME', 69911, 43.633157, -70.185305),
          place('4760280', 'Portland', 'Tennessee', 'TN', 13658, 36.597486, -86.526621),
          place('2371990', 'South Portland', 'Maine', 'ME', 27007, 43.631402, -70.285989),
        ]).bytes,
      ),
    );
    const names = (q: string, limit?: number): string[] =>
      places.search(q, limit).cities.map((h) => `${h.name}, ${h.state}`);

    it('goes ahead of the exact names it outweighs, which still follow', () => {
      expect(names('kansas')).toEqual([
        'Kansas City, MO',
        'Kansas City, KS',
        'Kansas, OK',
        'Kansas, IL',
        'Kansas, AL',
      ]);
      expect(names('kansas', 10).slice(5)).toEqual(['Kansas, OH', 'North Kansas City, MO']);
      expect(places.search('kansas').cities.every((h) => h.match === 'exact')).toBe(true);
    });

    it('needs the words where the name starts, and the weight', () => {
      // South Portland does not start with the word; it follows every Portland.
      expect(names('portland')).toEqual([
        'Portland, OR',
        'Portland, ME',
        'Portland, TN',
        'South Portland, ME',
      ]);
      expect(LEAD_FACTOR).toBeGreaterThan(27007 / 13658);
      // Two whole words: the exact names lead, and nothing named for them is heavy enough.
      expect(names('kansas city')).toEqual([
        'Kansas City, MO',
        'Kansas City, KS',
        'North Kansas City, MO',
      ]);
    });

    it('keeps its place in a state', () => {
      expect(names('kansas ok')[0]).toBe('Kansas, OK');
      expect(names('kansas mo')).toEqual(['Kansas City, MO', 'North Kansas City, MO']);
    });
  });

  describe('a name that starts with the words', () => {
    // Schools as the pipeline's directory has them (September 2026), enrollment as weight.
    const school = (
      id: string,
      name: string,
      sub: string,
      state: string,
      weight: number,
      lat: number,
      lon: number,
    ): SearchRecord => ({ kind: 'school', id, name, sub, state, lat, lon, weight });
    const schools = new SearchEngine(
      loadIndex(
        encodeIndex([
          school(
            '120018000230',
            'PEMBROKE PINES ELEMENTARY SCHOOL',
            'Pembroke Pines, FL',
            'FL',
            559,
            26.001842,
            -80.22124,
          ),
          school(
            '120018003307',
            'PEMBROKE PINES CHARTER ELEMENTARY SCHOOL',
            'Pembroke Pines, FL',
            'FL',
            2046,
            25.994698,
            -80.289443,
          ),
          school(
            '120018003544',
            'CITY/PEMBROKE PINES CHARTER MIDDLE SCHOOL',
            'Pembroke Pines, FL',
            'FL',
            1353,
            25.993762,
            -80.393524,
          ),
          school(
            '120018004318',
            'CITY/PEMBROKE PINES CHARTER HIGH SCHOOL',
            'Pembroke Pines, FL',
            'FL',
            2168,
            26.031479,
            -80.374666,
          ),
          school(
            '120018007807',
            'FRANKLIN ACADEMY PEMBROKE PINES',
            'Pembroke Pines, FL',
            'FL',
            1367,
            26.006209,
            -80.39931,
          ),
          school(
            '120018008456',
            'FRANKLIN ACADEMY PEMBROKE PINES HIGH SCHOOL',
            'Pembroke Pines, FL',
            'FL',
            1262,
            26.055707,
            -80.425,
          ),
          school(
            '330558000361',
            'Pembroke Hill School',
            'Pembroke, NH',
            'NH',
            312,
            43.157814,
            -71.464217,
          ),
          school(
            'A1902690',
            'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS',
            'Kansas City, MO',
            'MO',
            1174,
            39.03606,
            -94.593001,
          ),
        ]).bytes,
      ),
    );
    const names = (q: string, limit?: number): string[] =>
      schools.search(q, limit).schools.map((h) => h.name);

    it('goes ahead of a heavier name holding them further in, a leading "The" aside', () => {
      expect(names('pembroke')).toEqual([
        'PEMBROKE PINES CHARTER ELEMENTARY SCHOOL',
        'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS',
        'PEMBROKE PINES ELEMENTARY SCHOOL',
        'CITY/PEMBROKE PINES CHARTER HIGH SCHOOL',
        'FRANKLIN ACADEMY PEMBROKE PINES',
      ]);
      expect(names('pembroke hill')).toEqual([
        'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS',
        'Pembroke Hill School',
      ]);
    });

    it('stays behind a name START_FACTOR times heavier', () => {
      expect(START_FACTOR).toBe(4);
      // 312 students against 2168: the heavier names come first, Pembroke Hill School after them.
      const all = names('pembroke', 10);
      expect(all.indexOf('Pembroke Hill School')).toBeGreaterThan(
        all.indexOf('CITY/PEMBROKE PINES CHARTER HIGH SCHOOL'),
      );
      // The School District of Lancaster outweighs Lancaster Mennonite School more than four times over.
      expect(first('lancaster pa', 'schools')?.name).toBe('School District of Lancaster');
    });
  });

  describe('a name as the page shows it', () => {
    // Names as the pipeline's directory has them (September 2026).
    const record = (id: string, name: string, sub: string, state: string): SearchRecord => ({
      kind: 'school',
      id,
      name,
      sub,
      state,
      lat: 30,
      lon: -97,
      weight: 500,
    });
    const shown = new SearchEngine(
      loadIndex(
        encodeIndex([
          record('482364002589', 'TRAVIS EL', 'Austin, TX', 'TX'),
          record('050606000328', 'EL DORADO HIGH SCHOOL', 'El Dorado, AR', 'AR'),
          record('421185005236', 'Hershey Intrmd El Sch', 'Hershey, PA', 'PA'),
          record('A2104035', 'TEMPLE BETH EL SCHOOL', 'Richmond, VA', 'VA'),
        ]).bytes,
      ),
    );
    const found = (q: string): string[] => shown.search(q).schools.map((hit) => hit.name);

    it('finds its school, spelled out as shown', () => {
      expect(found('travis elementary')).toEqual(['TRAVIS EL']);
      expect(shown.search('travis elementary').schools[0]?.highlight).toEqual([
        [0, 6],
        [7, 9],
      ]);
      expect(found('hershey intermediate elementary school')).toEqual(['Hershey Intrmd El Sch']);
      expect(found('travis el')).toEqual(['TRAVIS EL']);
    });

    it('leaves El where it is a word', () => {
      expect(found('elementary')).toEqual(['Hershey Intrmd El Sch', 'TRAVIS EL']);
      expect(found('el dorado')).toEqual(['EL DORADO HIGH SCHOOL']);
      expect(found('beth elementary')).toEqual([]);
    });
  });

  it('puts exact before prefix before typo', () => {
    const r = engine.search('lancaster', 10).schools;
    const kinds = r.map((h) => h.match);
    expect(kinds.indexOf('prefix')).toBeGreaterThan(kinds.lastIndexOf('exact'));
    expect(r.find((h) => h.name === 'Lancasterville Elementary School')?.match).toBe('prefix');
  });

  it('matches every word as a prefix', () => {
    expect(first('lanc high', 'schools')?.name).toBe('Lancaster High School');
    expect(first('spr hi', 'schools')?.name).toBe('Springfield High School');
  });

  it('ranks names above places', () => {
    const r = engine.search('lancaster', 10).schools.map((h) => h.name);
    // McCaskey is in Lancaster but not named for it: after every named match.
    expect(r.indexOf('McCaskey Campus')).toBeGreaterThan(r.indexOf('Lancaster Mennonite School'));
    expect(r).toContain('McCaskey Campus');
  });

  it('finds a school by its place', () => {
    expect(ids('mccaskey lancaster', 'schools')).toEqual(['SYNS03']);
  });

  it('needs every word to match', () => {
    expect(engine.search('lancaster zebra').schools).toEqual([]);
  });

  it('ignores word order and case', () => {
    expect(ids('HIGH lancaster', 'schools')[0]).toBe('SYNS01');
  });

  it('keeps ties in a stable order', () => {
    expect(ids('oak hill', 'schools')).toEqual(['SYNS21', 'SYNS22', 'SYNS23']);
    expect(ids('oak hill', 'schools')).toEqual(ids('oak hill', 'schools'));
  });

  it('returns at most five per group by default', () => {
    expect(DEFAULT_LIMIT).toBe(5);
    expect(engine.search('school').schools).toHaveLength(5);
    expect(engine.search('school', 12).schools.length).toBeGreaterThan(5);
    expect(engine.search('school', 0).schools).toHaveLength(5);
    expect(engine.search('school', 1000).schools.length).toBeLessThanOrEqual(50);
  });

  it('echoes the query', () => {
    expect(engine.search('  Lancaster ').query).toBe('  Lancaster ');
  });
});

describe('typos', () => {
  it.each([
    ['lancastr', 'SYNC02'],
    ['lnacaster', 'SYNC02'],
    ['lancasterr', 'SYNC02'],
    ['philadelpia', 'SYNC19'],
    ['pitsburgh', 'SYNC18'],
    ['springfeild', 'SYNC07'],
  ])('%j finds %s', (q, id) => {
    const hit = first(q, 'cities');
    expect(hit?.id).toBe(id);
    expect(hit?.match).toBe('fuzzy');
  });

  it('allows two typos from eight characters', () => {
    expect(first('lncastre', 'cities')?.id).toBe('SYNC02');
  });

  it('allows one typo from four characters but not two', () => {
    expect(first('oakk hill', 'schools')?.name).toBe('Oak Hill Elementary School');
    expect(first('oak hilk', 'schools')?.name).toBe('Oak Hill Elementary School');
    expect(engine.search('oakkk hill').schools).toEqual([]);
  });

  it('allows no typo below four characters', () => {
    expect(engine.search('oxk').schools).toEqual([]);
  });

  it('corrects a typo that starts real words', () => {
    // "hight" starts no fixture word, but would still be read as "high".
    expect(first('hight school lancaster', 'schools')?.name).toBe('Lancaster High School');
    expect(first('lancastr hig', 'schools')?.name).toBe('Lancaster High School');
  });

  it('does not bend a common word into another', () => {
    // "portland" is spelled right: no Orlando.
    expect(ids('portland', 'cities')).toEqual(['SYNC14', 'SYNC15']);
  });

  it('never bends numbers', () => {
    expect(engine.search('17610').zips).toEqual([]);
  });
});

describe('states', () => {
  it.each(['lancaster pa', 'lancaster, pa', 'lancaster pennsylvania', 'lancaster, pennsylvania'])(
    '%j finds Lancaster, PA first',
    (q) => {
      expect(first(q, 'cities')?.id).toBe('SYNC01');
      expect(first(q, 'schools')?.sub).toBe('Lancaster, PA');
    },
  );

  it('keeps the plain reading too', () => {
    // "washington pa": Washington, PA and Washington Park.
    const cities = ids('washington pa', 'cities');
    expect(cities[0]).toBe('SYNC10');
    expect(cities).toContain('SYNC11');
  });

  it('reads multi-word state names', () => {
    expect(ids('new york new york', 'cities')[0]).toBe('SYNC08');
    expect(first('new york ny', 'cities')?.id).toBe('SYNC08');
  });

  it('reads a misspelled or unfinished state name', () => {
    expect(first('lancaster pensylvania', 'cities')?.id).toBe('SYNC01');
    expect(first('lancaster penn', 'cities')?.id).toBe('SYNC01');
  });

  it('lists a state by name when nothing else matches', () => {
    const cities = engine.search('pennsylvania').cities.map((h) => h.state);
    expect(cities.length).toBeGreaterThan(0);
    expect(new Set(cities)).toEqual(new Set(['PA']));
  });

  it('does not list a state for a bare code', () => {
    expect(engine.search('pa').cities.every((h) => h.name.toLowerCase().includes('pa'))).toBe(true);
  });

  it('keeps "st ma" for saints', () => {
    // Someone typing "St. Mary", not asking for Massachusetts.
    const names = engine.search('st ma').schools.map((h) => h.name);
    expect(names).toEqual(['Saint Marys Academy', "St. Mary's School"]);
  });
});

describe('ZIP codes', () => {
  it('finds a ZIP exactly', () => {
    expect(ids('17601', 'zips')).toEqual(['17601']);
    expect(first('17601', 'zips')?.match).toBe('exact');
  });

  it('finds ZIPs by prefix, in order', () => {
    expect(ids('176', 'zips')).toEqual(['17601', '17602', '17603']);
    expect(ids('17', 'zips')).toEqual(['17601', '17602', '17603', '17701']);
  });

  it('keeps leading zeros', () => {
    expect(ids('010', 'zips')).toEqual(['01002']);
  });

  it('puts ZIPs first for numeric input', () => {
    expect(engine.search('176').order).toEqual(['zips', 'schools', 'cities']);
    expect(engine.search('17601-1234').zips[0]?.id).toBe('17601');
  });

  it('still finds numbered schools', () => {
    expect(first('123', 'schools')?.name).toBe('P.S. 123 Mahalia Jackson');
  });

  it('filters ZIPs by state', () => {
    expect(ids('176 pa', 'zips')).toEqual(['17601', '17602', '17603']);
  });
});

describe('abbreviations', () => {
  it.each([
    ['lincoln hs', 'Lincoln HS'],
    ['lincoln high school', 'Lincoln HS'],
    ['lincoln hs', 'Lincoln High School'],
    ['lincoln elementary', 'Lincoln Elem'],
    ['lincoln elem', 'Lincoln Elem'],
    ['hans herr elementary school', 'Hans Herr El Sch'],
    ["saint mary's", "St. Mary's School"],
    ['st marys', 'Saint Marys Academy'],
    ['mount vernon', 'Mt. Vernon Intermediate School'],
    ['mt vernon is', 'Mt. Vernon Intermediate School'],
    ['lancaster independent school district', 'Lancaster ISD'],
    ['arts and sciences', 'Arts & Sciences Academy'],
    ['arts & sciences', 'Arts & Sciences Academy'],
  ])('%j finds %s', (q, name) => {
    expect(engine.search(q, 10).schools.map((h) => h.name)).toContain(name);
  });

  it('treats a spelled-out name as the whole name', () => {
    const cities = engine.search('saint marys').cities;
    expect(cities[0]?.name).toBe('St. Marys');
    expect(cities[0]?.match).toBe('exact');
  });
});

describe('spellings of one name', () => {
  // SYNTHETIC: a parish school spelled "Ann" among heavier "Anne" schools far away.
  const saint = (id: string, name: string, sub: string, weight: number, lat: number, lon: number) =>
    ({
      kind: 'school',
      id: `SYN${id}`,
      name,
      sub,
      state: sub.slice(-2),
      lat,
      lon,
      weight,
    }) as const;
  const records: SearchRecord[] = [
    saint('A1', 'St. Ann Catholic School', 'Prairie Village, KS', 400, 38.99, -94.63),
    ...Array.from({ length: 8 }, (_, i) =>
      saint(`A${String(i + 2)}`, 'ST ANNE SCHOOL', 'Lowell, MA', 900 + i, 42.6, -71.3),
    ),
    saint('A10', "St. John's School", 'Albany, NY', 500, 42.65, -73.75),
  ];
  const saints = new SearchEngine(loadIndex(encodeIndex(records).bytes));
  const nearKansasCity = { lat: 39.0, lon: -94.6, km: 40 };

  it.each(['Saint Anne', 'St Ann', "St. Anne's", 'st annes', "Saint Ann's", 'st anne'])(
    '%j finds St. Ann where the person is looking',
    (q) => {
      const hits = saints.search(q, 5, nearKansasCity).schools;
      expect(hits[0]?.id).toBe('SYNA1');
      expect(hits[0]?.match).not.toBe('fuzzy');
    },
  );

  it('finds a name without its possessive s', () => {
    expect(saints.search('st johns').schools.map((h) => h.id)).toContain('SYNA10');
    expect(saints.search('saint john').schools.map((h) => h.id)).toContain('SYNA10');
  });

  it('still puts the heavier exact spelling first nationally', () => {
    expect(saints.search('st anne').schools[0]?.name).toBe('ST ANNE SCHOOL');
  });
});

describe('a name and the town after it', () => {
  // SYNTHETIC: a suburb's parish school, the city people name it by, and a far namesake.
  const school = (id: string, name: string, sub: string, lat: number, lon: number) =>
    ({ kind: 'school', id, name, sub, state: sub.slice(-2), lat, lon, weight: 0 }) as const;
  const city = (id: string, name: string, state: string, lat: number, lon: number) =>
    ({ kind: 'city', id, name, sub: state, state, lat, lon, weight: 500_000 }) as const;
  const records: SearchRecord[] = [
    school('SYNT1', 'St. Ann Catholic School', 'Prairie Village, KS', 38.99, -94.63),
    school('SYNT2', 'ST ANNE SCHOOL', 'Lowell, MA', 42.6, -71.3),
    school('SYNT3', 'PARK HILL HIGH', 'Kansas City, MO', 39.2, -94.6),
    city('SYNC1', 'Kansas City', 'MO', 39.1, -94.58),
    city('SYNC2', 'Lowell', 'MA', 42.64, -71.32),
  ];
  const engine = new SearchEngine(loadIndex(encodeIndex(records).bytes));

  it.each([
    "St. Anne's Catholic school Kansas City",
    "Saint Anne's Catholic School in Kansas City",
    'st ann near kansas city',
  ])('%j finds the school near the city', (q) => {
    const r = engine.search(q);
    expect(r.schools.map((h) => h.id)).toEqual(['SYNT1']);
    expect(r.cities.map((h) => h.id)).toEqual(['SYNC1']);
    expect(r.order[0]).toBe('schools');
  });

  it('lists only the schools near that town', () => {
    expect(engine.search('st anne lowell').schools.map((h) => h.id)).toEqual(['SYNT2']);
    expect(engine.search('st anne catholic kansas city').schools.map((h) => h.id)).toEqual([
      'SYNT1',
    ]);
  });

  it('finds nothing when no town ends the query or none of its schools match', () => {
    expect(engine.search('st anne springfield').schools).toEqual([]);
    expect(engine.search('holy cross kansas city').schools).toEqual([]);
  });

  it('leaves a query that finds schools as it is', () => {
    expect(engine.search('park hill kansas city').schools.map((h) => h.id)).toEqual(['SYNT3']);
    expect(engine.search('kansas city').cities[0]?.id).toBe('SYNC1');
  });
});

describe('a name, the town after it and its state, or a ZIP code', () => {
  // SYNTHETIC: one parish school in a Kansas suburb, the two Kansas Citys (the
  // Missouri one heavier), a far namesake, and the suburb's ZIP code; two
  // Springfields, each with a St. Agnes in a town near it.
  const school = (id: string, name: string, sub: string, lat: number, lon: number) =>
    ({ kind: 'school', id, name, sub, state: sub.slice(-2), lat, lon, weight: 0 }) as const;
  const city = (id: string, name: string, state: string, w: number, lat: number, lon: number) =>
    ({ kind: 'city', id, name, sub: state, state, lat, lon, weight: w }) as const;
  const records: SearchRecord[] = [
    school('SYNS1', 'St. Ann Catholic School', 'Prairie Village, KS', 38.99, -94.63),
    school('SYNS2', 'ST ANNE SCHOOL', 'Lowell, MA', 42.6, -71.3),
    school('SYNS4', 'ST AGNES SCHOOL', 'Chatham, IL', 39.68, -89.7),
    school('SYNS5', 'ST AGNES SCHOOL', 'Republic, MO', 37.12, -93.48),
    city('SYNP1', 'Springfield', 'MO', 170_000, 37.21, -93.29),
    city('SYNP2', 'Springfield', 'IL', 115_000, 39.8, -89.65),
    city('SYNK1', 'Kansas City', 'MO', 500_000, 39.1, -94.58),
    city('SYNK2', 'Kansas City', 'KS', 150_000, 39.11, -94.63),
    city('SYNK3', 'Kansas', 'OK', 800, 36.2, -94.79),
    {
      kind: 'zip',
      id: '66208',
      name: '66208',
      sub: 'Kansas',
      state: 'KS',
      lat: 38.99,
      lon: -94.63,
      weight: 0,
    },
  ];
  const engine = new SearchEngine(loadIndex(encodeIndex(records).bytes));
  const ids = (q: string): string[] => engine.search(q).schools.map((h) => h.id);

  it.each([
    "Saint Anne's Catholic School Kansas City KS",
    "Saint Anne's Catholic School Kansas City, Kansas",
    'St Ann Kansas City Kansas',
    'st ann catholic kansas city, ks',
  ])('%j reads the state as a choice of town, not a word of the name', (q) => {
    const r = engine.search(q);
    expect(r.schools.map((h) => h.id)).toEqual(['SYNS1']);
    expect(r.cities[0]?.id).toBe('SYNK2');
    expect(r.order[0]).toBe('schools');
  });

  it('chooses the town in the state typed', () => {
    expect(ids('st agnes springfield il')).toEqual(['SYNS4']);
    expect(ids('st agnes school springfield, illinois')).toEqual(['SYNS4']);
    expect(ids('st agnes springfield mo')).toEqual(['SYNS5']);
    // With no state, the larger town.
    expect(ids('st agnes springfield')).toEqual(['SYNS5']);
    expect(engine.search('st ann kansas city mo').cities[0]?.id).toBe('SYNK1');
    // No Kansas City in Iowa: nothing near any.
    expect(ids('st ann catholic kansas city ia')).toEqual([]);
  });

  it.each(['St Ann 66208', "saint anne's catholic school 66208"])(
    '%j reads a ZIP code as the place',
    (q) => {
      const r = engine.search(q);
      expect(r.schools.map((h) => h.id)).toEqual(['SYNS1']);
      expect(r.zips[0]?.id).toBe('66208');
      expect(r.order).toEqual(['schools', 'zips', 'cities']);
    },
  );

  it('finds nothing near a ZIP code no school of the name is near', () => {
    expect(ids('st anne 66208')).toEqual(['SYNS1']);
    expect(ids('holy cross 66208')).toEqual([]);
    expect(ids('st ann 99999')).toEqual([]);
  });
});

describe('a town whose name ends with another town', () => {
  // SYNTHETIC: towns named for a neighbour ("Old Mystic", "Ben Avon"), each with no
  // school of its name, and schools near the neighbour whose names have its first word.
  const school = (id: string, name: string, sub: string, lat: number, lon: number) =>
    ({ kind: 'school', id, name, sub, state: sub.slice(-2), lat, lon, weight: 0 }) as const;
  const city = (id: string, name: string, state: string, w: number, lat: number, lon: number) =>
    ({ kind: 'city', id, name, sub: state, state, lat, lon, weight: w }) as const;
  const records: SearchRecord[] = [
    city('SYNM1', 'Old Mystic', 'CT', 4_000, 41.39, -71.96),
    city('SYNM2', 'Mystic', 'CT', 9_000, 41.35, -71.97),
    school('SYNM3', 'OLD SAYBROOK SCHOOL', 'Old Saybrook, CT', 41.29, -72.38),
    city('SYNB1', 'Ben Avon', 'PA', 1_800, 40.51, -80.08),
    city('SYNB2', 'Avon', 'OH', 24_000, 41.45, -82.04),
    school('SYNB3', 'ST BENEDICT CATHOLIC SCHOOL', 'Garfield Heights, OH', 41.42, -81.61),
    city('SYNW1', 'West University Place', 'TX', 15_000, 29.72, -95.43),
    city('SYNW2', 'University Place', 'WA', 34_000, 47.24, -122.55),
    school('SYNW3', 'WEST AUBURN SENIOR HIGH SCHOOL', 'Auburn, WA', 47.3, -122.23),
  ];
  const engine = new SearchEngine(loadIndex(encodeIndex(records).bytes));

  it.each([
    ['Old Mystic', 'SYNM1'],
    ['old myst', 'SYNM1'],
    ['Ben Avon', 'SYNB1'],
    ['ben avo', 'SYNB1'],
    ['West University Place', 'SYNW1'],
    ['west university pl', 'SYNW1'],
    ['Old Mystic CT', 'SYNM1'],
    ['Old Mystic, Connecticut', 'SYNM1'],
    ['Ben Avon PA', 'SYNB1'],
    ['West University Place TX', 'SYNW1'],
  ])('%j lists that town first, and no school of another town', (q, id) => {
    const r = engine.search(q);
    expect(r.cities[0]?.id).toBe(id);
    expect(r.schools).toEqual([]);
  });

  it('still reads a name and the town when no town has the whole name', () => {
    const r = engine.search('st benedict avon');
    expect(r.schools.map((h) => h.id)).toEqual(['SYNB3']);
    expect(r.cities[0]?.id).toBe('SYNB2');
  });
});

describe('a final s', () => {
  // SYNTHETIC: "Hills" names a light school; a heavy "Hill" one must not outrank it.
  const records: SearchRecord[] = [
    {
      kind: 'school',
      id: 'SYNH1',
      name: 'PARK HILL HIGH',
      sub: 'Kansas City, MO',
      state: 'MO',
      lat: 39.2,
      lon: -94.6,
      weight: 3000,
    },
    {
      kind: 'school',
      id: 'SYNH2',
      name: 'Forest Hills School',
      sub: 'Grand Rapids, MI',
      state: 'MI',
      lat: 42.9,
      lon: -85.5,
      weight: 100,
    },
  ];
  const engine = new SearchEngine(loadIndex(encodeIndex(records).bytes));

  it('is part of the word', () => {
    const hits = engine.search('hills').schools;
    expect(hits[0]?.id).toBe('SYNH2');
    expect(hits.find((h) => h.id === 'SYNH1')?.match ?? 'none').not.toBe('exact');
  });
});

describe('accents and punctuation', () => {
  it.each([
    ['canon city', 'SYNC12'],
    ['cañon city', 'SYNC12'],
    ['CAÑON CITY', 'SYNC12'],
    ['cañon', 'SYNC12'],
  ])('%j finds Cañon City', (q, id) => {
    expect(first(q, 'cities')?.id).toBe(id);
  });

  it.each([
    ['espanola', 'Española Valley High School'],
    ["o'neill", "O'Neill Middle School"],
    ['oneill', "O'Neill Middle School"],
    ['o neill', "O'Neill Middle School"],
    ['p.s. 123', 'P.S. 123 Mahalia Jackson'],
    ['ps 123', 'P.S. 123 Mahalia Jackson'],
  ])('%j finds %s', (q, name) => {
    expect(engine.search(q, 10).schools.map((h) => h.name)).toContain(name);
  });
});

describe('odd input', () => {
  it.each([
    '',
    ' ',
    '     \t  ',
    '🙂',
    '🏫🏫🏫',
    '---',
    '\u0000\u0001',
    '\ud800',
    '學校',
    'x'.repeat(10_000),
    'lancaster '.repeat(200),
    '%%%***',
  ])('handles %j without error', (q) => {
    const r = engine.search(q);
    expect(r.query).toBe(q);
    expect(total(r)).toBeLessThanOrEqual(15);
  });

  it('finds nothing for input without words', () => {
    expect(total(engine.search('🙂 ---'))).toBe(0);
    expect(total(engine.search('   '))).toBe(0);
  });

  it('matches text around emoji', () => {
    expect(first('🏫 lancaster 🏫', 'cities')?.id).toBe('SYNC02');
  });
});

describe('results', () => {
  it('carries what the detail panel needs', () => {
    const hit = first('mccaskey', 'schools');
    expect(hit).toMatchObject({
      kind: 'school',
      id: 'SYNS03',
      name: 'McCaskey Campus',
      sub: 'Lancaster, PA',
      state: 'PA',
      match: 'exact',
    });
    expect(hit?.lat).toBeCloseTo(40.05, 4);
    expect(hit?.lon).toBeCloseTo(-76.29, 4);
  });

  it('marks districts', () => {
    expect(first('school district of lancaster', 'schools')?.kind).toBe('district');
  });

  it('orders groups by their best match', () => {
    expect(engine.search('lancaster').order).toEqual(['cities', 'schools', 'zips']);
    expect(engine.search('mccaskey').order[0]).toBe('schools');
  });

  it('puts places first when a place and a district are both named exactly as typed', () => {
    // As pipeline/out/site-data/search and the directory have them (September 2026).
    const record = (
      kind: SearchRecord['kind'],
      id: string,
      name: string,
      sub: string,
      state: string,
      weight: number,
    ): SearchRecord => ({ kind, id, name, sub, state, lat: 39.1, lon: -94.6, weight });
    const kc = new SearchEngine(
      loadIndex(
        encodeIndex([
          record('city', '2938000', 'Kansas City', 'Missouri', 'MO', 521220),
          record('city', '2036000', 'Kansas City', 'Kansas', 'KS', 157805),
          record('district', '2007950', 'Kansas City', 'Kansas City, KS', 'KS', 21000),
          record('district', '2916400', 'KANSAS CITY 33', 'Kansas City, MO', 'MO', 14000),
          record(
            'school',
            'A1902690',
            'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS',
            'Kansas City, MO',
            'MO',
            1200,
          ),
        ]).bytes,
      ),
    );
    const results = kc.search('kansas city');
    expect(results.order).toEqual(['cities', 'schools', 'zips']);
    expect(results.cities.map((h) => h.id)).toEqual(['2938000', '2036000']);
    expect(results.schools[0]?.id).toBe('2007950');
    // Names only a school has still put schools first.
    expect(kc.search('pembroke').order[0]).toBe('schools');
  });

  it('highlights the matched part of each word', () => {
    expect(first('lanc hi', 'schools')?.highlight).toEqual([
      [0, 4],
      [10, 12],
    ]);
    expect(first("o'ne", 'schools')?.highlight).toEqual([[0, 4]]);
    // The name's "St." stands for the query's "saint".
    expect(first('saint marys', 'cities')?.highlight).toEqual([
      [0, 2],
      [4, 9],
    ]);
  });

  it('highlights typo matches', () => {
    const ranges = highlight('Lancaster High School', [{ text: 'lancastr', budget: 2 }], 2);
    expect(ranges).toEqual([[0, 9]]);
  });
});

describe('near where the person is looking', () => {
  // As the directory and the places build have them (September 2026), weights made up for size.
  const record = (
    kind: SearchRecord['kind'],
    id: string,
    name: string,
    sub: string,
    state: string,
    lat: number,
    lon: number,
    weight: number,
  ): SearchRecord => ({ kind, id, name, sub, state, lat, lon, weight });
  const pembroke = new SearchEngine(
    loadIndex(
      encodeIndex([
        record('city', '1257425', 'Pembroke Pines', 'Florida', 'FL', 26.0128, -80.3382, 171178),
        record('city', '3751000', 'Pembroke', 'North Carolina', 'NC', 34.6816, -79.1953, 2823),
        record('school', '2509660', 'Pembroke', 'Pembroke, MA', 'MA', 42.0624, -70.8033, 3000),
        record(
          'school',
          '330579000321',
          'Pembroke Academy',
          'Pembroke, NH',
          'NH',
          43.1476,
          -71.4556,
          900,
        ),
        record(
          'school',
          'A1902690',
          'The Pembroke Hill School - Wornall Campus',
          'Kansas City, MO',
          'MO',
          39.03606,
          -94.593001,
          600,
        ),
        record(
          'school',
          '290000000001',
          'Lincoln Elementary',
          'Kansas City, MO',
          'MO',
          39.05,
          -94.6,
          500,
        ),
      ]).bytes,
    ),
  );
  const kansasCity = { lat: 39.1, lon: -94.58, km: 100 };

  it('lists the records named so near it first, their group first', () => {
    const near = pembroke.search('pembroke', 5, kansasCity);
    expect(near.order[0]).toBe('schools');
    expect(near.schools.map((hit) => hit.id)).toEqual(['A1902690', '2509660', '330579000321']);
    expect(near.cities.map((hit) => hit.id)).toEqual(['1257425', '3751000']);
  });

  it('changes nothing from far away, or with nothing near', () => {
    const plain = pembroke.search('pembroke', 5);
    expect(plain.schools.map((hit) => hit.id)).toEqual(['2509660', '330579000321', 'A1902690']);
    expect(pembroke.search('pembroke', 5, { lat: 47.6, lon: -122.3, km: 100 })).toEqual(plain);
  });

  it('leaves a record near it that only its place matches where it was', () => {
    // Lincoln Elementary is in Kansas City, but its name has no Kansas in it.
    const near = pembroke.search('kansas city', 5, kansasCity);
    expect(near.schools[0]?.id).toBe('A1902690');
    expect(near).toEqual(pembroke.search('kansas city', 5));
  });
});

describe('names as the page shows them', () => {
  // As the directory has them (September 2026), with the names the page shows them by
  // (stage-data.mjs); weights made up for size.
  const school = (
    id: string,
    name: string,
    shown: string | undefined,
    sub: string,
    state: string,
    lat: number,
    lon: number,
    weight: number,
  ): SearchRecord => ({
    kind: 'school',
    id,
    name,
    ...(shown === undefined ? {} : { shown }),
    sub,
    state,
    lat,
    lon,
    weight,
  });
  const shownEngine = new SearchEngine(
    loadIndex(
      encodeIndex([
        school(
          '290061203365',
          'MIDDLE SCHOOL',
          'Citizens of the World Charter - Middle School',
          'Kansas City, MO',
          'MO',
          39.0646,
          -94.5899,
          200,
        ),
        school(
          '290061203286',
          'ELEMENTARY SCHOOL',
          'Citizens of the World Charter - Elementary School',
          'Kansas City, MO',
          'MO',
          39.0646,
          -94.5899,
          400,
        ),
        school(
          '290738000311',
          'MIDDLE SCHOOL',
          'Carrollton R-VII - Middle School',
          'Carrollton, MO',
          'MO',
          39.3688,
          -93.4901,
          250,
        ),
        school(
          '060205012708',
          'Citizens of the World Charter School Hollywood',
          undefined,
          'Los Angeles, CA',
          'CA',
          34.0949,
          -118.3176,
          500,
        ),
        {
          kind: 'district',
          id: '2900612',
          name: 'CITIZENS OF THE WORLD CHARTER',
          sub: 'Kansas City, MO',
          state: 'MO',
          lat: 39.0646,
          lon: -94.5899,
          weight: 600,
        },
        school(
          '290002502748',
          'ALLEN VILLAGE ELEMENTARY ACADE',
          'Allen Village Elementary Academy',
          'Kansas City, MO',
          'MO',
          39.0529,
          -94.5948,
          300,
        ),
        school(
          '290002503325',
          'ALLEN VILLAGE JUNIOR ACADEMY',
          undefined,
          'Kansas City, MO',
          'MO',
          39.0529,
          -94.5948,
          100,
        ),
        school(
          '170019006798',
          'Five County Reg Voc Center',
          'Five County Regional Vocational Center',
          'Ullin, IL',
          'IL',
          37.2316,
          -89.271,
          50,
        ),
      ]).bytes,
    ),
  );
  const found = (q: string): string[] => shownEngine.search(q, 10).schools.map((hit) => hit.id);

  it('finds a school by its name exactly as shown, first and as an exact name', () => {
    const results = shownEngine.search('Citizens of the World Charter - Middle School', 10);
    expect(results.schools[0]?.id).toBe('290061203365');
    expect(results.schools[0]?.match).toBe('exact');
    expect(found('Allen Village Elementary Academy')[0]).toBe('290002502748');
    expect(found('five county regional vocational center')).toEqual(['170019006798']);
  });

  it('finds it by some of the words it is shown by', () => {
    expect(found('citizens middle')).toEqual(['290061203365']);
    expect(found('citizens of the world charter elementary')[0]).toBe('290061203286');
    expect(found('citizens of the world')).toEqual(
      expect.arrayContaining(['290061203365', '290061203286', '060205012708', '2900612']),
    );
    expect(found('carrollton middle')).toEqual(['290738000311']);
  });

  it('still finds it by its name as written', () => {
    expect(found('middle school').slice(0, 2).sort()).toEqual(['290061203365', '290738000311']);
    expect(found('allen village elementary acade')[0]).toBe('290002502748');
    expect(found('five county reg voc')).toEqual(['170019006798']);
  });

  it('marks the match in the shown name', () => {
    const hit = shownEngine.search('citizens middle', 10).schools[0];
    expect(hit?.shown).toBe('Citizens of the World Charter - Middle School');
    const marked = (hit?.shownHighlight ?? []).map(([a, b]) => hit?.shown?.slice(a, b));
    expect(marked).toEqual(['Citizens', 'Middle']);
    expect(hit?.highlight.map(([a, b]) => hit.name.slice(a, b))).toEqual(['MIDDLE']);
    const allen = shownEngine.search('allen village acade', 10).schools[0];
    expect((allen?.shownHighlight ?? []).map(([a, b]) => allen?.shown?.slice(a, b))).toEqual([
      'Allen',
      'Village',
      'Acade',
    ]);
    // A record the page shows as written has no shown name to mark.
    expect(shownEngine.search('hollywood', 10).schools[0]).not.toHaveProperty('shown');
  });
});
