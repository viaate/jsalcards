import { describe, expect, it } from 'vitest';

import { alikeDistricts, districtName } from '../district-names';

/** The words a family says, as the panel says them when no other district of the state shares them. */
function words(shown: string, state: string | null = null): string | null {
  return districtName(shown, state).words;
}

describe('a district’s name', () => {
  it('leaves out the whole of its kind, never a word of it', () => {
    // Illinois, as NCES writes it (the panel's names, from the real directory).
    expect(words('Indian Prairie CUSD 204')).toBe('Indian Prairie');
    expect(words('Indian Prairie Community Unit School District 204')).toBe('Indian Prairie');
    expect(words('Woodlawn Unit School District 209')).toBe('Woodlawn');
    expect(words('St. Anne Unit District 24')).toBe('St. Anne');
    expect(words('Joliet PSD 86')).toBe('Joliet');
    expect(words('Downers Grove GSD 58')).toBe('Downers Grove');
    expect(words('Fox Lake GSD 114')).toBe('Fox Lake');
    expect(words('Hononegah CHD 207')).toBe('Hononegah');
    expect(words('Goreville CUD 1')).toBe('Goreville');
    expect(words('Dwight Common School District 232')).toBe('Dwight');
    expect(words('Hinsdale Township HSD 86')).toBe('Hinsdale');
    expect(words('Hinsdale Township High School District 86')).toBe('Hinsdale');
    // Union high schools, in California, Vermont, Oregon and Wisconsin.
    expect(words('Acalanes Union High')).toBe('Acalanes');
    expect(words('Chaffey Joint Union High')).toBe('Chaffey');
    expect(words('Lake Region Union High School District #24')).toBe('Lake Region');
    expect(words('Mount Anthony Union High School District #14')).toBe('Mount Anthony');
    expect(words('Harney County Union High School District 1J')).toBe('Harney County');
    expect(words('Nicolet Union High School School District')).toBe('Nicolet');
    expect(words('Penn Valley Union Elementary')).toBe('Penn Valley');
    expect(words('Rocklin Unified')).toBe('Rocklin');
    expect(words('Lowell Joint')).toBe('Lowell');
    expect(words('Olentangy Local')).toBe('Olentangy');
    expect(words('Bowling Green Independent')).toBe('Bowling Green');
    expect(words('Shawnee Mission Public Schools')).toBe('Shawnee Mission');
    expect(words('Katy ISD')).toBe('Katy');
  });

  it('takes its number apart, however the state writes it', () => {
    expect(districtName('Chicago Ridge School District 127-5')).toMatchObject({
      words: 'Chicago Ridge',
      number: '127-5',
    });
    expect(districtName('Posen-Robbins ESD 143-5')).toMatchObject({ number: '143-5' });
    expect(districtName('Tri Point CUSD 6-J')).toMatchObject({ words: 'Tri Point', number: '6-J' });
    expect(districtName('Weld County School District No. Re-4')).toMatchObject({
      words: 'Weld County',
      number: 'Re-4',
    });
    expect(districtName('Crowley County School District No. Re-1-J')).toMatchObject({
      number: 'Re-1-J',
    });
    expect(districtName('Bayfield School District No. 10Jt-R')).toMatchObject({ number: '10Jt-R' });
    expect(districtName('Archuleta County School District No. 50 Jt')).toMatchObject({
      words: 'Archuleta County',
      number: '50',
    });
    expect(districtName('Moffat County School District RE: No. 1')).toMatchObject({
      words: 'Moffat County',
      number: '1',
    });
    expect(districtName('Converse County School District #1')).toMatchObject({ number: '1' });
  });

  it('leaves out what only the state’s records add: an id, the county it lies in', () => {
    expect(districtName('Flagstaff Unified District (4192)')).toEqual({
      words: 'Flagstaff',
      number: null,
      whole: 'Flagstaff Unified District',
      named: 'Flagstaff Unified',
    });
    expect(words('Show Low Unified District (4393)')).toBe('Show Low');
    expect(words('Tempe Preparatory Academy (4361)')).toBe('Tempe Preparatory Academy');
    expect(words('Cherry Creek School District No. 5 in the county of Arapah')).toBe(
      'Cherry Creek',
    );
    expect(words('Center Consolidated School District No. 26 Jt. of the count')).toBe('Center');
    expect(words('Lewis-Palmer Consolidated School District No. 38 in the co')).toBe(
      'Lewis-Palmer',
    );
    // A name that leads with its kind: the place after it, or the county it names.
    expect(districtName('School District No. 1 in the county of Denver and State')).toMatchObject({
      words: 'Denver',
      number: '1',
    });
    expect(words('School District N. 14 in the county of Adams & State of Colo')).toBe('Adams');
    expect(words('School District No. Re-2 Brush')).toBe('Brush');
    expect(words('School District No. Re-3 Fort Morgan')).toBe('Fort Morgan');
    expect(words('GreeleySchool District No. 6 in the county of Weld and Sta')).toBe('Greeley');
  });

  it('stays whole where its words alone would name no place, or say no kind', () => {
    // Nothing but its kind and number: the page says the number's district.
    expect(districtName('Cusd 300')).toEqual({
      words: null,
      number: '300',
      whole: 'Cusd 300',
      named: 'Cusd 300',
    });
    expect(districtName('Township HSD 214')).toMatchObject({ words: null, number: '214' });
    expect(districtName('Community Unit School District No 196')).toMatchObject({
      words: null,
      number: '196',
    });
    expect(words('Community Unit School District')).toBe('Community Unit School District');
    expect(words('Public Schools')).toBe('Public Schools');
    // A word that is no place alone: the whole name, or the word with its number.
    expect(words('Central Local')).toBe('Central Local');
    expect(words('Union Local')).toBe('Union Local');
    expect(words('Central ISD')).toBe('Central ISD');
    expect(districtName('United CUSD 304')).toMatchObject({ words: 'United 304', number: null });
    expect(words('School District No. Re-1 Valley')).toBe('Valley Re-1');
    // Places whose words carry a kind's word stay as they are.
    expect(words('Union County Public Schools')).toBe('Union County');
    expect(words('Interstate 35 Community School District')).toBe('Interstate 35');
    expect(words('Kansas City 33 School District')).toBe('Kansas City 33');
    // A district of one school is its name.
    expect(words('Presidio School')).toBe('Presidio School');
    // A kind's word with its number is a name: never "District R-VI".
    expect(districtName('Community R-VI', 'MO')).toMatchObject({
      words: 'Community R-VI',
      number: null,
    });
    expect(words('Center 58', 'MO')).toBe('Center 58');
    expect(words('Valley R-VI', 'MO')).toBe('Valley R-VI');
    // A number that is a school's, a kind's or Maine's unit's, with no place before it.
    expect(words('Phalen Leadership Academy at Louis B Russell School 48', 'IN')).toBe(
      'Phalen Leadership Academy at Louis B Russell School 48',
    );
    expect(words('Custer County School District Consolidate 1', 'CO')).toBe(
      'Custer County School District Consolidate 1',
    );
    expect(words('Rsu 16', 'ME')).toBe('Rsu 16');
    expect(words('Boces 5', 'WY')).toBe('Boces 5');
    // A word that is no place alone keeps the kind's words that make it one.
    expect(words('Valley Central School District (Montgomery)', 'NY')).toBe('Valley Central');
    expect(words('Southern Regional School District', 'NJ')).toBe('Southern Regional');
    expect(words('Northeast Community School District', 'IA')).toBe('Northeast Community');
    expect(words('Southwest Public Schools', 'NE')).toBe('Southwest Public Schools');
  });

  it('reads the kinds of the big snow states: New York, Montana, New England, Ohio', () => {
    // New York's central school districts, with the name or place it adds after.
    expect(words('Dolgeville Central School District', 'NY')).toBe('Dolgeville');
    expect(words('Beaver River Central School District', 'NY')).toBe('Beaver River');
    expect(words('Broadalbin-Perth Central School District', 'NY')).toBe('Broadalbin-Perth');
    expect(words('Bellmore-Merrick Central High School District', 'NY')).toBe('Bellmore-Merrick');
    expect(words('Gorham-Middlesex Central School District (Marcus Whitman)', 'NY')).toBe(
      'Gorham-Middlesex',
    );
    expect(words('Delaware Academy Central School District at Delhi', 'NY')).toBe(
      'Delaware Academy',
    );
    expect(words('Lowville Academy & Central School District', 'NY')).toBe('Lowville Academy');
    expect(districtName('New York City Geographic District #32', 'NY')).toMatchObject({
      words: 'New York City',
      number: '32',
    });
    // Elsewhere "Central" is the name: Manheim Central, Prairie Central.
    expect(words('Manheim Central School District', 'PA')).toBe('Manheim Central');
    expect(words('Prairie Central CUSD 8', 'IL')).toBe('Prairie Central');
    // And so is the county a name gives, where two districts would read the same without it.
    expect(words('WESTSIDE SCHOOL DISTRICT (Johnson)', 'AR')).toBe(
      'WESTSIDE SCHOOL DISTRICT (Johnson)',
    );
    // Montana's K-12 schools.
    expect(words('Baker K-12 Schools', 'MT')).toBe('Baker');
    expect(words('Ennis K-12 Schools', 'MT')).toBe('Ennis');
    expect(words('East Helena K-12', 'MT')).toBe('East Helena');
    // Regional districts, in Massachusetts, New Hampshire, New Jersey and Arizona.
    expect(words('Monomoy Regional School District', 'MA')).toBe('Monomoy');
    expect(words('Up-Island Regional', 'MA')).toBe('Up-Island');
    expect(words('Assabet Valley Regional Vocational Technical', 'MA')).toBe('Assabet Valley');
    expect(words('Southern Worcester County Regional Vocational School District', 'MA')).toBe(
      'Southern Worcester County',
    );
    expect(words('Timberlane Regional School District', 'NH')).toBe('Timberlane');
    expect(words('Gila County Regional School District (87600)', 'AZ')).toBe('Gila County');
    // Ohio's community city districts.
    expect(words('Springboro Community City', 'OH')).toBe('Springboro');
    expect(words('Deer Park Community City', 'OH')).toBe('Deer Park');
  });

  it('takes a number that follows no kind apart: Missouri, the Dakotas, South Carolina', () => {
    // The Kansas City metro, as the directory writes it.
    for (const [name, place, number] of [
      ['Blue Springs R-IV', 'Blue Springs', 'R-IV'],
      ["Lee's Summit R-VII", "Lee's Summit", 'R-VII'],
      ['Raytown C-2', 'Raytown', 'C-2'],
      ['Hickman Mills C-1', 'Hickman Mills', 'C-1'],
      ['North Kansas City 74', 'North Kansas City', '74'],
      ['Kansas City 33', 'Kansas City', '33'],
      ['Independence 30', 'Independence', '30'],
      ['Liberty 53', 'Liberty', '53'],
      ['Wheaton R-III', 'Wheaton', 'R-III'],
    ] as const) {
      expect(districtName(name, 'MO')).toMatchObject({ words: place, number });
    }
    expect(districtName('Grand Forks 1', 'ND')).toMatchObject({
      words: 'Grand Forks',
      number: '1',
    });
    expect(districtName('Lexington 01', 'SC')).toMatchObject({ words: 'Lexington', number: '01' });
    expect(districtName('Massac UD 1', 'IL')).toMatchObject({ words: 'Massac', number: '1' });
    expect(districtName('Easton Township S/D #6', 'MI')).toMatchObject({
      words: 'Easton Township',
      number: '6',
    });
  });

  it('never ends on a word that joins or leads into more of the name', () => {
    // A kind's words after "and" or a dash were the name's own.
    expect(words('Interdistrict School for Arts and Community District', 'CT')).toBe(
      'Interdistrict School for Arts and Community',
    );
    expect(words('Oxford Preparatory Academy - Middle District', 'CA')).toBe(
      'Oxford Preparatory Academy - Middle',
    );
    // Only a noun or a number after them: those go.
    expect(words('Penta Career Center - District', 'OH')).toBe('Penta Career Center');
    expect(districtName('NYC Special Schools - District 75', 'NY')).toMatchObject({
      words: 'NYC Special Schools',
      number: '75',
    });
    // "Of" leads into what the cut took: whole.
    expect(words('Madera County Superintendent of Schools', 'CA')).toBe(
      'Madera County Superintendent of Schools',
    );
    // Michigan's city districts, their place cut off after "of the City of".
    expect(words('Flint School District of the City of', 'MI')).toBe('Flint');
    expect(words('Harper Woods The School District of the City of', 'MI')).toBe('Harper Woods');
    expect(words('Muskegon Public Schools of the City of', 'MI')).toBe('Muskegon');
  });

  it('keeps the kind’s words where they are what tells two apart', () => {
    expect(districtName('Franklin Regional School District', 'PA').named).toBe('Franklin Regional');
    expect(districtName('Franklin Area School District', 'PA').named).toBe('Franklin Area');
    expect(districtName('Corning Union High', 'CA').named).toBe('Corning Union High');
  });
});

describe('districts named alike', () => {
  it('are those of one state whose words are the same, whatever their kinds', () => {
    const district = (id: string, state: string, shown: string) => ({ id, state, shown });
    expect(
      alikeDistricts([
        district('a', 'IL', 'Hinsdale CCSD 181'),
        district('b', 'IL', 'Hinsdale Township HSD 86'),
        district('c', 'IL', 'Lyons School District 103'),
        district('d', 'IL', 'Lyons Township HSD 204'),
        district('e', 'IL', 'Indian Prairie CUSD 204'),
        district('f', 'IA', 'Pekin Community School District'),
        district('g', 'IL', 'Pekin PSD 108'),
        district('h', 'IL', 'Cusd 300'),
        district('i', 'IL', 'CCSD 300'),
        district('j', 'CA', 'Corning Union High'),
        district('k', 'CA', 'Corning Union Elementary'),
        district('l', 'MO', 'Grandview C-4'),
        district('m', 'MO', 'Grandview R-II'),
        district('n', 'MO', 'Kansas City 33'),
        district('o', 'KS', 'Kansas City'),
        district('p', 'NY', 'Perry Central School District'),
        district('q', 'OH', 'Perry Local'),
      ]),
    ).toEqual(['a', 'b', 'c', 'd', 'j', 'k', 'l', 'm']);
  });
});
