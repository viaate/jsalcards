import { describe, expect, it } from 'vitest';

import { casedName, displayName, nameLayout, shownRanges } from '../names';

describe('displayName', () => {
  it('shows a name written in capitals in title case', () => {
    expect(displayName('THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS')).toBe(
      'The Pembroke Hill School - Wornall Campus',
    );
    expect(displayName('BORDER STAR MONTESSORI')).toBe('Border Star Montessori');
    expect(displayName('CLEMENTINE MONTESSORI SCHOOL')).toBe('Clementine Montessori School');
  });

  it('shows a run of spaces NCES left in a name as one space', () => {
    expect(displayName('M. L. King  Elementary')).toBe('M. L. King Elementary');
    expect(displayName('MANUAL CAREER  TECH. CENTER ')).toBe('Manual Career Tech. Center');
    expect(displayName('ROSS  EL SCH')).toBe('Ross Elementary School');
  });

  it('keeps the case of a name with any lowercase letter', () => {
    for (const name of [
      'Kate D Smith DAR High School',
      'KIPP Endeavor Academy',
      'McKinley Elementary',
    ]) {
      expect(displayName(name)).toBe(name);
    }
  });

  it('spells out the shortenings the notes list, in place', () => {
    expect(displayName('Ross El Sch')).toBe('Ross Elementary School');
    expect(displayName('Lancaster Catholic HS')).toBe('Lancaster Catholic High School');
    expect(displayName('McCall Gen George A Sch')).toBe('McCall Gen George A School');
    expect(displayName('Philadelphia Performing Arts CS')).toBe(
      'Philadelphia Performing Arts Charter School',
    );
    expect(displayName('Penn View MS')).toBe('Penn View Middle School');
    expect(displayName('LINCOLN JHS')).toBe('Lincoln Junior High School');
    expect(displayName('Noble St Chtr-Rowe-Clark MS Acad')).toBe(
      'Noble St Charter-Rowe-Clark Middle School Academy',
    );
  });

  it('spells out the other standard NCES shortenings', () => {
    expect(displayName('SMITH EL')).toBe('Smith Elementary');
    expect(displayName('Lincoln Elem')).toBe('Lincoln Elementary');
    expect(displayName('BELLE ELEM.')).toBe('Belle Elementary');
    expect(displayName('WASHINGTON ES')).toBe('Washington Elementary School');
    expect(displayName('Friendship PCS - Collegiate Academy')).toBe(
      'Friendship Public Charter School - Collegiate Academy',
    );
    expect(displayName('Towanda Area JSHS')).toBe('Towanda Area Junior-Senior High School');
    expect(displayName('East Stroudsburg SHS North')).toBe(
      'East Stroudsburg Senior High School North',
    );
    expect(displayName('COLMESNEIL JH/HS')).toBe('Colmesneil Junior High/High School');
    expect(displayName('Drums El/MS')).toBe('Drums Elementary/Middle School');
    expect(displayName('ALVARADO EL-SOUTH')).toBe('Alvarado Elementary-South');
    expect(displayName('Hershey Intrmd El Sch')).toBe('Hershey Intermediate Elementary School');
    expect(displayName('BARBERS HILL INT')).toBe('Barbers Hill Intermediate');
    expect(displayName('LA VEGA PRI')).toBe('La Vega Primary');
    expect(displayName('Curtisville Pri Ctr')).toBe('Curtisville Primary Center');
    expect(displayName('MARTIN LUTHER KING JR LEARNING CTR')).toBe(
      'Martin Luther King Jr Learning Center',
    );
    expect(displayName('ST JOHN THE BAPTIST SCH')).toBe('St John the Baptist School');
    expect(displayName('Shaker Hts High School')).toBe('Shaker Heights High School');
    expect(displayName('PASEO ACAD. OF PERFORMING ARTS')).toBe('Paseo Academy of Performing Arts');
  });

  it('spells out the shortenings left over after the first pass', () => {
    expect(displayName('Decatur Pub. Schs. Alt. Education')).toBe(
      'Decatur Public Schools Alternative Education',
    );
    expect(displayName('MSD Southwest Allen County Schls')).toBe(
      'MSD Southwest Allen County Schools',
    );
    expect(displayName('Evanston Twp High School')).toBe('Evanston Township High School');
    expect(displayName('Carbondale Comm H S')).toBe('Carbondale Community High School');
    expect(displayName('LEE A. TOLBERT COM. ACADEMY')).toBe('Lee A. Tolbert Community Academy');
    expect(displayName('North Harrison Com School Corp')).toBe(
      'North Harrison Community School Corp',
    );
    expect(displayName('COLLEGE STATION H S')).toBe('College Station High School');
    expect(displayName('PREMIER H S OF WACO')).toBe('Premier High School of Waco');
    expect(displayName('ST LAURENCE H.S.')).toBe('St Laurence High School');
    expect(displayName('BOOKER JH/H S')).toBe('Booker Junior High/High School');
    expect(displayName('Butler Co. Area Technology Center')).toBe(
      'Butler County Area Technology Center',
    );
    expect(displayName('BERGEN CO JDC')).toBe('Bergen County JDC');
  });

  it('reads Pub Sch in a district’s name as the Public Schools the district is', () => {
    expect(displayName('Shawnee Mission Pub Sch', { state: 'KS', district: true })).toBe(
      'Shawnee Mission Public Schools',
    );
    expect(displayName('Valley Center Pub Sch', { state: 'KS', district: true })).toBe(
      'Valley Center Public Schools',
    );
    expect(displayName('SHAWNEE MISSION PUB. SCH.', { district: true })).toBe(
      'Shawnee Mission Public Schools',
    );
    // A public charter school is one school; a school's name keeps its School.
    expect(
      displayName('AMIGOS POR VIDA-FRIENDS FOR LIFE PUB CHTR SCH', { state: 'WI', district: true }),
    ).toBe('Amigos Por Vida-Friends for Life Public Charter School');
    expect(displayName('Shawnee Mission Pub Sch')).toBe('Shawnee Mission Public School');
    expect(displayName('Shawnee Mission Pub Sch', { district: false })).toBe(
      'Shawnee Mission Public School',
    );
    // Only the Sch after Pub: a district's other shortenings read as they always do.
    expect(displayName('Ross Sch Dist', { district: true })).toBe('Ross School District');
    expect(displayName('Decatur Pub. Schs. Alt. Education', { district: true })).toBe(
      'Decatur Public Schools Alternative Education',
    );
    // A search match of the written Sch marks Schools, and one of its Sc the Sc of Schools.
    const raw = 'Shawnee Mission Pub Sch';
    const layout = nameLayout(raw, { district: true });
    expect(shownRanges(layout, raw, [[20, 23]])).toEqual([[23, 30]]);
    expect(shownRanges(layout, raw, [[20, 22]])).toEqual([[23, 25]]);
  });

  it('spells out every shortening the directory uses a few times, where it has one meaning', () => {
    const shown: [string, string][] = [
      ['Quincy Area Voc Ctr', 'Quincy Area Vocational Center'],
      ['Chana Educ Center/Rock River', 'Chana Education Center/Rock River'],
      ['ROE Alt. Edu. Center-Macoupin', 'ROE Alternative Education Center-Macoupin'],
      ['ESCAMBIA SCH. DIST. JAIL PROG.', 'Escambia School District Jail Program'],
      ['West 40 Reg Safe Sch Middle Prg', 'West 40 Regional Safe School Middle Program'],
      ['New Beginnings Regnl Safe Sch Pgm', 'New Beginnings Regional Safe School Program'],
      ['Coop HS 1', 'Cooperative HS 1'],
      ['Lozano Elem Bilingual & Intl Ctr', 'Lozano Elementary Bilingual & International Center'],
      ['Univ of Chicago Chtr-Woodlawn', 'University of Chicago Charter-Woodlawn'],
      ['Home & Hosp/Transition Support', 'Home & Hospital/Transition Support'],
      ['Treasure Mtn. Junior High School', 'Treasure Mountain Junior High School'],
      ['Regl Inst Scholastic Excellence', 'Regional Institute Scholastic Excellence'],
      ['STUBBLEFIELD LRN CTR', 'Stubblefield Learning Center'],
      ['HUMBOLDT ACAD OF HIGHER LRNING', 'Humboldt Academy of Higher Learning'],
      ["ONONDAGA CNTY SHERIFF'S DEPT", "Onondaga County Sheriff's Department"],
      ['Twin Cities German Immersion Chrtr', 'Twin Cities German Immersion Charter'],
      ['Hiawatha Leadership Acdy-Northrop', 'Hiawatha Leadership Academy-Northrop'],
      ['Crown Elem Comm Acd Fine Arts Ctr', 'Crown Elementary Community Academy Fine Arts Center'],
      ['Mary D Lang Kdg Ctr', 'Mary D Lang Kindergarten Center'],
      ['GREEN FOREST INTERMED SCHOOL', 'Green Forest Intermediate School'],
      ['WASHINGTON IRVING INTERM SCHOOL', 'Washington Irving Intermediate School'],
      ['CONG. MIKOR HATORAH', 'Congregation Mikor Hatorah'],
      ['South Mountain Secure Trmnt Unit', 'South Mountain Secure Treatment Unit'],
      ["WOMEN'S EAST REGION TRTMT CTR", "Women's East Region Treatment Center"],
      ['Plymouth Commun Intermediate', 'Plymouth Community Intermediate'],
      ['Gaylord High SchoolVoc Bldg', 'Gaylord High SchoolVoc Building'],
      ['PALM AVENUE EXCEP. STUDENT CENTER', 'Palm Avenue Exceptional Student Center'],
      ['LOCKWOOD SPECL. EDUC. COOP.', 'Lockwood Special Education Cooperative'],
      ['Pine Hills Youth Corr Facil HS', 'Pine Hills Youth Correctional Facility High School'],
      ['AD Johnston JrSr High School', 'AD Johnston Junior-Senior High School'],
      ['WESTERN RECEPT/DIAG CORR CENTR', 'Western Reception/Diagnostic Correctional Center'],
      ['Dimmick Comm Cons SD 175', 'Dimmick Community Consolidated School District 175'],
      [
        'The SD of Philadelphia Virtual Academy',
        'The School District of Philadelphia Virtual Academy',
      ],
      ['Pike Road Jr High School', 'Pike Road Junior High School'],
      ['Music Mountain Jr./Sr. High School', 'Music Mountain Junior/Senior High School'],
      ['Zion-Benton Twnshp Hi Sch', 'Zion-Benton Township High School'],
      ['GIFT - Ft. Thomas High School', 'GIFT - Fort Thomas High School'],
      ['Wm E Bishop Elementary School', 'William E Bishop Elementary School'],
      ['IZARD COUNTY CONS MIDDLE SCHOOL', 'Izard County Consolidated Middle School'],
      ['Ogden Ave Elem School', 'Ogden Avenue Elementary School'],
      ['MARION REG. JUVENILE DETENTION CENTER', 'Marion Regional Juvenile Detention Center'],
      ['Levy Sp Ed Center', 'Levy Special Education Center'],
      ['JUVENILE JUSTICE CENTER ALT ED', 'Juvenile Justice Center Alternative Education'],
      ['Old National Trail Spec Serv Coop', 'Old National Trail Special Services Cooperative'],
      ['CENTRAL VISUAL/PERF. ARTS HIGH', 'Central Visual/Performing Arts High'],
      [
        'Ivy Bound Acad of Math Sci and Tech Charter Mid',
        'Ivy Bound Academy of Math Science and Tech Charter Middle',
      ],
      ['Belgrade-Brooten-Elrosa Sec.', 'Belgrade-Brooten-Elrosa Secondary'],
      ['PINELLAS JUVENILE DET CENTER', 'Pinellas Juvenile Detention Center'],
      ['Vermilion Co Area Vocational Cent', 'Vermilion County Area Vocational Center'],
      ['Person Early College Innovation & Ldrshp', 'Person Early College Innovation & Leadership'],
      ['Mt Carmel Elementary School', 'Mount Carmel Elementary School'],
      ['GIFT - Mt. Graham High School', 'GIFT - Mount Graham High School'],
      ['RUSSELL BLVD. ELEM.', 'Russell Boulevard Elementary'],
      ['Sandshore Rd. Elementary School', 'Sandshore Road Elementary School'],
      ['GREENE CTY TECH HIGH SCHOOL', 'Greene County Tech High School'],
      ['BRAZORIA CO ALTER ED CTR', 'Brazoria County Alternative Education Center'],
      ['NORTH HEIGHTS ALTER', 'North Heights Alternative'],
    ];
    for (const [written, expected] of shown) expect(displayName(written)).toBe(expected);
  });

  it('spells out the rest the directory uses, each where it has one meaning', () => {
    const shown: [string, string, string?][] = [
      [
        'Crenshaw Sci Tech Engr Math and Med Magnet',
        'Crenshaw Science Tech Engineering Math and Med Magnet',
      ],
      [
        'Env Academy of Research Tech and Earth Scis',
        'Environmental Academy of Research Tech and Earth Sciences',
      ],
      ['Hope D Wall TMH Child Dev Ctr', 'Hope D Wall TMH Child Development Center'],
      ['Paradise Prof Dev ES', 'Paradise Professional Development Elementary School'],
      ['Indiana Academy for Sci Math Hmn', 'Indiana Academy for Science Math Humanities'],
      ['Hoover Elementary BioMed Sci Egng', 'Hoover Elementary BioMed Science Engineering'],
      [
        'Cesar E. Chavez Learning Acads-Soc Just Humanitas Academy',
        'Cesar E. Chavez Learning Academies-Social Justice Humanitas Academy',
      ],
      ['KIPP Chicago Chrtrs - Ascend Acad', 'KIPP Chicago Charters - Ascend Academy'],
      ['Christopher House Chrt ES', 'Christopher House Charter Elementary School'],
      ['Asian Human Srvcs-Passage Chrtr', 'Asian Human Services-Passage Charter'],
      ['Southside Sp Srvs Of Marion Co', 'Southside Special Services Of Marion Co'],
      ['Alternative Spcl Needs Div Occ', 'Alternative Special Needs Div Occ'],
      ['MT Sch For Deaf & Blnd HS', 'Montana School For Deaf & Blind High School', 'MT'],
      ['IN School for the Blind & Vis Imprd', 'IN School for the Blind & Visually Impaired'],
      ['Lincoln Cltrl Ctr-Montessori Elem', 'Lincoln Cultural Center-Montessori Elementary'],
      ['Thornton Fractnl No High School', 'Thornton Fractional No High School'],
      [
        'Linda Esperanza Marquez High A Hntngtn Park Inst of Appl Med',
        'Linda Esperanza Marquez High A Huntington Park Institute of Applied Med',
      ],
      ['N Pekin & Marquette Hght SD 102', 'N Pekin & Marquette Heights School District 102'],
      ['Boothbay-Boothbay Hbr CSD', 'Boothbay-Boothbay Harbor CSD'],
      ['Tri-County Sp Ed Jnt Agreement', 'Tri-County Special Education Joint Agreement'],
      ['Univ of Chicago Chtr-Nth Kenwood', 'University of Chicago Charter-North Kenwood'],
      ['Harrisburg HS - SciTech Cmp', 'Harrisburg High School - SciTech Campus'],
      [
        'Matanzas Christian Academy Priv School Sys Inc',
        'Matanzas Christian Academy Private School System Inc',
      ],
      ['Hillsborough Virt Instr PRGS', 'Hillsborough Virtual Instr Programs'],
      ['283-Ind Stdy 15 and Under - I.S.', '283-Independent Study 15 and Under - I.S.'],
      ['Fridley Moore Lk Area Learning Ctr', 'Fridley Moore Lake Area Learning Center'],
      ['Pt. Pleasant Primary', 'Point Pleasant Primary'],
      ['BASIS SAN ANTONIO PRI - NORTHEAST CAMPUS', 'Basis San Antonio Primary - Northeast Campus'],
      ['LA VEGA PRI PHIL BANCALE CAMPUS', 'La Vega Primary Phil Bancale Campus'],
      ['PRI DAEP', 'Primary DAEP'],
      ['Perspectives Chtr - Leadership Ac', 'Perspectives Charter - Leadership Academy'],
      ['Mount Ascension Learning Ac HS', 'Mount Ascension Learning Academy High School'],
      ['ARKANSAS CHRISTIAN AC', 'Arkansas Christian Academy'],
      ['HIGHER HEIGHTS CHRISTIAN ACA', 'Higher Heights Christian Academy'],
      [
        'Kaizen Education Foundation dba Liberty Arts Acade (90334)',
        'Kaizen Education Foundation dba Liberty Arts Academy (90334)',
      ],
      ['TARPON SPRINGS FUNDAMENTAL ELE', 'Tarpon Springs Fundamental Elementary'],
      ['RED BIRD CHRISTIAN SCHO', 'Red Bird Christian School'],
      [
        'ST VINCENT DE PAUL DUAL LANGUAGE IMMERSION SCHOO',
        'St Vincent De Paul Dual Language Immersion School',
      ],
      ['Jeannette Rankin Elementary Sc', 'Jeannette Rankin Elementary School'],
      ['MADGE T. JAMES KIND. CTR.', 'Madge T. James Kindergarten Center'],
      [
        'REYNOLDA PRESBYTERIAN PRESCHOOL AND KIND',
        'Reynolda Presbyterian Preschool and Kindergarten',
      ],
      ['GENTRY RESIDENTIAL TREAT. FAC.', 'Gentry Residential Treatment Facility'],
      [
        'Gr Lawrence Regional Vocational Technical',
        'Greater Lawrence Regional Vocational Technical',
      ],
      ['Raymore-Peculiar Ninth Gr Cntr', 'Raymore-Peculiar Ninth Grade Center'],
      [
        'South Shore International Col Prep High School',
        'South Shore International College Prep High School',
      ],
      ['LAMAR CONS H S', 'Lamar Consolidated High School'],
      ['Mundelein Cons HSD 120', 'Mundelein Consolidated HSD 120'],
      [
        'Wilmington Mid Sci Tech Engr Arts Math (STEAM) Magnet',
        'Wilmington Middle Science Tech Engineering Arts Math (STEAM) Magnet',
      ],
    ];
    for (const [written, expected, state] of shown) {
      expect(displayName(written, { state: state ?? null })).toBe(expected);
    }
  });

  it('keeps acronyms that only look like words in capitals', () => {
    expect(displayName('ACADEMIE LAFAYETTE ARMOUR IHS')).toBe('Academie Lafayette Armour IHS');
    expect(displayName('ST BARNABAS CATHOLIC SCHOOL IMS')).toBe('St Barnabas Catholic School IMS');
    expect(displayName('ELK CITY IES')).toBe('Elk City IES');
    expect(displayName('CROSBYTON CISD PRE K-12')).toBe('Crosbyton CISD Pre K-12');
    expect(displayName('VISD SUCCESS ACADEMY')).toBe('VISD Success Academy');
    expect(displayName('EBISD WCJJAEP')).toBe('EBISD WCJJAEP');
  });

  it('leaves a shortening where it has another meaning', () => {
    // Named for a man, not a grade.
    expect(displayName('MARTIN LUTHER KING JR HIGH SCHOOL')).toBe(
      'Martin Luther King Jr High School',
    );
    expect(displayName('Cloves C Campbell Sr Elementary School')).toBe(
      'Cloves C Campbell Sr Elementary School',
    );
    // Ed Pastor, Mid Valley, Corr the family, Spec. the rank, South Dakota's SD.
    expect(displayName('Ed Pastor Elementary 4')).toBe('Ed Pastor Elementary 4');
    expect(displayName('Mid Valley Alternative Charter')).toBe('Mid Valley Alternative Charter');
    expect(displayName('CORR ELEMENTARY SCHOOL')).toBe('Corr Elementary School');
    expect(displayName('SPEC RAFAEL HERNANDO MIDDLE')).toBe('Spec Rafael Hernando Middle');
    expect(displayName('SD SCH FOR THE DEAF')).toBe('SD School for the Deaf');
    // Mountain View or Mount View; an ordinal's ending; Alter the archbishop.
    expect(displayName('Mt View Middle School')).toBe('Mt View Middle School');
    expect(displayName('63RD ST MULTICULTURAL ACAD')).toBe('63rd St Multicultural Academy');
    expect(displayName('ARCHBISHOP ALTER HIGH SCHOOL')).toBe('Archbishop Alter High School');
    // Tech is Technical or Technology, St Saint or Street, Int International or Intermediate,
    // Med Medicine or Medical, Spec Special or Specialty.
    expect(displayName('63RD ST MULTICULTURAL ACAD')).toBe('63rd St Multicultural Academy');
    expect(displayName('Ogden Int High School')).toBe('Ogden Int High School');
    expect(displayName('COLLEGIATE SCHOOL OF MED/BIO')).toBe('Collegiate School of Med/Bio');
    expect(displayName('Reavis Elem Math & Sci Spec Schl')).toBe(
      'Reavis Elementary Math & Science Spec School',
    );
    // A person's name, a program's own, a first word, a grade with its numbers.
    expect(displayName('SCHOO MIDDLE SCHOOL')).toBe('Schoo Middle School');
    expect(displayName('NTSH PRI PROGRAM WICHITA CAMPUS')).toBe('NTSH Pri Program Wichita Campus');
    expect(displayName('AC PREP ELEMENTARY')).toBe('Ac Prep Elementary');
    expect(displayName('FAC CHRISTIAN SCHOOL')).toBe('Fac Christian School');
    expect(displayName('LaCrescent Gr 9-12')).toBe('LaCrescent Gr 9-12');
    expect(displayName('Col. J. K. Tuffree Middle')).toBe('Col. J. K. Tuffree Middle');
    expect(displayName('Jeannette Rankin Elementary Sc', { state: 'SC' })).toBe(
      'Jeannette Rankin Elementary Sc',
    );
  });

  it("spells out a school's own state, by its code", () => {
    expect(displayName('MO SCHLS FOR THE SEV DISABLED', { state: 'MO' })).toBe(
      'Missouri Schools for the Severely Disabled',
    );
    expect(displayName('WESTERN MO CORRECTIONAL CENTER', { state: 'MO' })).toBe(
      'Western Missouri Correctional Center',
    );
    expect(displayName('UNIVERSITY OF MO - COLUMBIA', { state: 'MO' })).toBe(
      'University of Missouri - Columbia',
    );
    expect(displayName('MN Online High School - I.S.', { state: 'MN' })).toBe(
      'Minnesota Online High School - I.S.',
    );
    expect(displayName('SD SCH FOR THE BLIND & VISUALLY IMPAIRED', { state: 'SD' })).toBe(
      'South Dakota School for the Blind & Visually Impaired',
    );
    // A code that is also a word, a name or another shortening stays: Colorado's CO is County too.
    expect(displayName('LA SCHOOL FOR AG SCIENCE', { state: 'LA' })).toBe(
      'LA School for Ag Science',
    );
    expect(displayName('KIPP DC - KEY Academy PCS', { state: 'DC' })).toBe(
      'KIPP DC - KEY Academy Public Charter School',
    );
    // Only the school's own state, and never a small word.
    expect(displayName('WESTERN MO CORRECTIONAL CENTER')).toBe('Western Mo Correctional Center');
    expect(displayName('SCHOOL IN THE WOODS', { state: 'IN' })).toBe('School in the Woods');
    expect(displayName('HOPE ONLINE LEARNING ACADEMY CO-OP', { state: 'CO' })).toBe(
      'Hope Online Learning Academy Co-Op',
    );
  });

  it('leaves words that only look like shortenings', () => {
    expect(displayName('EL DORADO HIGH SCHOOL')).toBe('El Dorado High School');
    expect(displayName('John Adams Academy - El Dorado Hills')).toBe(
      'John Adams Academy - El Dorado Hills',
    );
    expect(displayName('TEMPLE BETH EL SCHOOL')).toBe('Temple Beth El School');
    expect(displayName('RALEIGH PRIMARY/EL ACADEMY')).toBe('Raleigh Primary/El Academy');
    expect(displayName('CS Brown High - STEM Program')).toBe('CS Brown High - STEM Program');
    // Initials, a pub, communication arts, a co-op.
    expect(displayName('H S THOMPSON LEARNING CENTER')).toBe('H S Thompson Learning Center');
    expect(displayName('THE PUB ACADEMY')).toBe('The Pub Academy');
    expect(displayName('Bradwell Comm Arts & Sci Elem Sch')).toBe(
      'Bradwell Comm Arts & Science Elementary School',
    );
    expect(displayName('RIVER VALLEY CO-OP SCHOOL')).toBe('River Valley Co-Op School');
    expect(displayName('K12.COM ACADEMY')).toBe('K12.Com Academy');
    expect(displayName('CO SPRINGS ACADEMY')).toBe('Co Springs Academy');
    expect(displayName("SOUTHWEST PUBLIC SCHOOLS INT'L LEADERSHIP ACADEMY")).toBe(
      "Southwest Public Schools Int'l Leadership Academy",
    );
    expect(displayName('ACCELERATED INT CHARTER SCHOOL')).toBe('Accelerated Int Charter School');
    expect(displayName('Clark County Detention Ctr J-SHS')).toBe(
      'Clark County Detention Center J-SHS',
    );
    expect(displayName('NEX GEN ACADEMY')).toBe('Nex Gen Academy');
    // Lowercase letters are words, not shortenings.
    expect(displayName('Ms. Smith Preschool')).toBe('Ms. Smith Preschool');
  });

  it('keeps the letters of a numbered New York City school', () => {
    expect(displayName('PS 123 JOHN H GLENN')).toBe('PS 123 John H Glenn');
    expect(displayName('JHS 167 ROBERT F WAGNER')).toBe('JHS 167 Robert F Wagner');
    expect(displayName('MS 45 THOMAS C GIORDANO')).toBe('MS 45 Thomas C Giordano');
    expect(displayName('IS 289')).toBe('IS 289');
  });

  it('keeps MS as the state in Mississippi', () => {
    expect(displayName('MS School For The Blind', { state: 'MS' })).toBe('MS School For The Blind');
    expect(displayName('NORTHEAST MS REGIONAL ALTERNATIVE', { state: 'MS' })).toBe(
      'Northeast MS Regional Alternative',
    );
    expect(displayName('NORTHEAST MS REGIONAL ALTERNATIVE')).toBe(
      'Northeast Middle School Regional Alternative',
    );
  });

  it('keeps acronyms, initials and Roman numerals in capitals', () => {
    expect(displayName('KIPP:DELTA COLLEGE PREP SCHOOL')).toBe('KIPP:Delta College Prep School');
    expect(displayName('HOLY FAMILY ACADEMY II')).toBe('Holy Family Academy II');
    expect(displayName('IDEA STEM ACADEMY LLC')).toBe('IDEA STEM Academy LLC');
  });

  it('lowercases small words after the first', () => {
    expect(displayName('THE ACADEMY OF ARTS AND SCIENCES')).toBe(
      'The Academy of Arts and Sciences',
    );
  });

  it('handles Mc names, apostrophes and ordinals', () => {
    expect(displayName('MCKINLEY ELEMENTARY')).toBe('McKinley Elementary');
    expect(displayName("ST. MARY'S SCHOOL")).toBe("St. Mary's School");
    expect(displayName("O'NEILL INT'L ACADEMY")).toBe("O'Neill Int'l Academy");
    expect(displayName("GIRLS' PREP")).toBe("Girls' Prep");
    expect(displayName('21ST CENTURY 6TH GRADE CENTER')).toBe('21st Century 6th Grade Center');
  });

  it('keeps letters outside A to Z whole', () => {
    expect(displayName('ESCUELA ESPAÑOLA')).toBe('Escuela Española');
    expect(displayName('ÉCOLE FRANÇAISE')).toBe('École Française');
  });

  it('never adds, drops or moves a word', () => {
    const letters = (text: string): string => text.toUpperCase().replace(/[^A-Z0-9]/g, '');
    const names = [
      'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS',
      "O'NEILL INT'L ACADEMY",
      'Friendship PCS - Collegiate Academy',
      'Ross El Sch',
      'Carbondale Comm H S',
      'ST LAURENCE H.S.',
    ];
    for (const name of names) {
      const layout = nameLayout(name);
      // The pieces cover the written name in order, and only spelled-out pieces change letters.
      expect(layout.map((piece) => name.slice(piece.from, piece.to)).join('')).toBe(name);
      for (const piece of layout.filter((p) => !p.spelled)) {
        expect(letters(piece.text)).toBe(letters(name.slice(piece.from, piece.to)));
      }
    }
  });
});

describe('casedName', () => {
  it('changes only case, so the text keeps its length and letters', () => {
    const names = [
      'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS',
      "O'NEILL INT'L ACADEMY",
      'İSTANBUL ACADEMY',
      '21ST CENTURY 6TH GRADE CENTER',
      'LANCASTER HS',
      '',
      '64113',
    ];
    for (const name of names) {
      const shown = casedName(name);
      expect(shown).toHaveLength(name.length);
      expect(shown.toUpperCase()).toBe(name.toUpperCase());
    }
    expect(casedName('KANSAS CITY')).toBe('Kansas City');
    expect(casedName('ST LOUIS')).toBe('St Louis');
    expect(casedName('Kansas City')).toBe('Kansas City');
  });
});

describe('shownRanges', () => {
  const ranges = (raw: string, marked: [number, number][]): string[] => {
    const layout = nameLayout(raw);
    const shown = layout.map((piece) => piece.text).join('');
    return shownRanges(layout, raw, marked).map(([start, end]) => shown.slice(start, end));
  };

  it('carries a match over to the shown name', () => {
    const raw = 'THE PEMBROKE HILL SCHOOL - WORNALL CAMPUS';
    expect(ranges(raw, [[4, 12]])).toEqual(['Pembroke']);
    expect(
      ranges(raw, [
        [4, 12],
        [13, 17],
      ]),
    ).toEqual(['Pembroke', 'Hill']);
  });

  it('marks the words a matched shortening stands for', () => {
    expect(ranges('Ross El Sch', [[0, 4]])).toEqual(['Ross']);
    expect(ranges('Ross El Sch', [[8, 11]])).toEqual(['School']);
    expect(ranges('Ross El Sch', [[8, 10]])).toEqual(['Sc']);
    expect(ranges('Lancaster Catholic HS', [[19, 21]])).toEqual(['High School']);
    expect(ranges('Lancaster Catholic HS', [[19, 20]])).toEqual(['High School']);
    expect(
      ranges('Ross El Sch', [
        [5, 7],
        [8, 11],
      ]),
    ).toEqual(['Elementary', 'School']);
  });

  it('marks both words of a two-word shortening', () => {
    expect(ranges('Carbondale Comm H S', [[16, 17]])).toEqual(['High School']);
    expect(ranges('Carbondale Comm H S', [[0, 10]])).toEqual(['Carbondale']);
  });

  it('keeps ranges after a spelled-out word in place', () => {
    expect(ranges('Lincoln Elem Magnet', [[13, 19]])).toEqual(['Magnet']);
    expect(ranges('PASEO ACAD. OF PERFORMING ARTS', [[15, 25]])).toEqual(['Performing']);
  });
});
