/**
 * School, district and place names as the page shows them.
 *
 * NCES writes about four in ten school names in capitals ("THE PEMBROKE HILL
 * SCHOOL - WORNALL CAMPUS") and shortens many ("Ross El Sch", "Lancaster
 * Catholic HS"). The page shows them in title case, with the standard
 * shortenings spelled out ("The Pembroke Hill School - Wornall Campus",
 * "Ross Elementary School", "Lancaster Catholic High School"). No word is
 * added, dropped or moved: each shortening becomes the words it stands for,
 * in its place. Search matches the names as NCES writes them; `shownRanges`
 * carries a match in the written name over to the shown one.
 *
 * Case (`casedName`, the only change for places): a name written in capitals
 * is shown in title case; a name with any lowercase letter keeps its case.
 * Within a capitalized name:
 * - the code of the school's own state stays in capitals where it stands for
 *   the state (MO in "WESTERN MO CORRECTIONAL CENTER", a Missouri school);
 * - acronyms stay in capitals: words with no vowel (PS, HS, JHS, LLC), a list
 *   of common ones that have vowels (KIPP, STEM, ISD), and Roman numerals;
 * - single letters stay capitals (initials such as the H in JOHN H GLENN);
 * - the usual short forms with no vowel are title-cased (ST, JR, CTR, SCH);
 * - "of", "the", "and", "at", "for", "in", "on" and "to" are lowercase after
 *   the first word;
 * - McX names become McX (MCKINLEY: McKinley);
 * - after an apostrophe, one or two letters are lowercase (MARY'S, INT'L)
 *   and a longer word is title-cased (O'NEILL: O'Neill);
 * - ordinal endings after a number are lowercase (21ST: 21st).
 *
 * Shortenings (school and district names, `displayName`), each only where
 * NCES uses it for these words:
 * - Sch, Schl: School; Schls, Schs: Schools; Elem: Elementary; Acad: Academy;
 *   Ctr: Center; Chtr: Charter; Intrmd: Intermediate; Lrng: Learning;
 *   Hts: Heights; Twp: Township;
 * - Pub: Public before School, Schools or Charter ("Decatur Pub. Schs."); in
 *   a district's name, Pub Sch is Public Schools, as the two districts that
 *   have it call themselves ("Shawnee Mission Pub Sch", "Valley Center Pub
 *   Sch"; but "... Pub Chtr Sch" is a Public Charter School);
 * - Com, Comm: Community, but before Arts ("Bradwell Comm Arts & Sci");
 * - Co: County after a name, never first or joined by a hyphen ("Butler Co.
 *   Area Technology Center", but "Co-op");
 * - H S: High School, never at the start of a name, where they are initials
 *   ("Carbondale Comm H S", "Premier H.S. of Waco");
 * - El: Elementary before School or another school, or at the end of a name
 *   or part of one ("Ross El Sch", "SMITH EL", "Drums El/MS"), never in "El
 *   Dorado" or "Beth El";
 * - in capitals: HS, MS, JHS, JH, SHS, JSHS, ES, CS (Charter School), PCS
 *   (Public Charter School); INT (Intermediate) and PRI (Primary) where a
 *   name ends with them;
 * - a numbered New York City school keeps its letters ("PS 15", "MS 45",
 *   "JHS 22"), and Mississippi's names keep MS, its state.
 * A period that ends a shortening goes with it ("ELEM." is "Elementary").
 *
 * The rest of the shortenings the 2024-25 directory uses at least a few
 * times, counted over its 118,132 school and 18,227 district names (the
 * count after each), each only where it has one meaning:
 * - anywhere: Voc Vocational (47), Educ and Edu Education (48), Dist and Dst
 *   District (95), Pgm, Prg, Prgm and Prog Program (31), Alt Alternative
 *   (44), Coop Cooperative (35), Intl International (22), Engr Engineering
 *   (14), Univ University (12), Hosp Hospital (12), Mtn Mountain (12), Inst
 *   Institute (11), Lrn and Lrning Learning (17), Dept Department (9), Diag
 *   Diagnostic (8), Cnty County (7), Chrtr Charter (6), Acd and Acdy Academy
 *   (8), Kdgn and Kdg Kindergarten (7), Intermed and Interm Intermediate (7),
 *   Recep and Recept Reception (5), Cong Congregation (5), Trmnt and Trtmt
 *   Treatment (5), Regnl, Regl and Rgnl Regional (4), Commun Community (4),
 *   Bldg Building (3), Cmps Campus (3), Excep Exceptional (3), Specl Special
 *   (3), Juv and Jvnl Juvenile (3), Facil Facility (2), Mdle Middle (1),
 *   JrSr Junior-Senior (23);
 * - SD, in capitals, School District (937), unless the school is in South
 *   Dakota; Jr and Sr Junior and Senior before High, Hi, HS or each other
 *   (769), but not after King ("Martin Luther King Jr High"); Hi High after
 *   them or before School; Ft Fort (37) and Wm William (17) before a name;
 *   Cons Consolidated (36) next to Comm, County or a school word; Ave Avenue
 *   (28) after a name; Reg Regional (16) inside a name; Ed Education (in
 *   "Sp Ed", "Alt Ed", "Ed Center"), Sp and Spec Special before it; Perf
 *   Performing before Arts (9); Mt Mount before a name (242), but not before
 *   View or Valley, as often Mountain's; Blvd Boulevard (7), Rd Road (11) and
 *   Cty County (9) after a word; Alter Alternative (24) before Ed, Ctr, Prog,
 *   H S or School, or ending a name; Mid Middle before School, High or And, or
 *   ending a name (64 in all, "Mid Valley" aside); Sec Secondary ending a
 *   name or before School, Career or Center (13); Corr Correctional (7) and
 *   Det Detention (6) where they name a facility; Sev Severely before
 *   Disabled;
 * - the code of the school's own state, in capitals, where it stands for the
 *   state ("MO School for the Blind": Missouri; 150 or so), for the codes
 *   that are not also words, particles or other shortenings.
 *
 * And the rest the directory uses, counted the same way, each where it has
 * one meaning:
 * - anywhere: Sci Science (50), Scis Sciences (3), Dev Development (15), Env
 *   Environmental (4), Acads Academies (4), Sys System (3), Hmn Humanities,
 *   Chrtrs Charters, Blnd Blind, Imprd Impaired, Srvs and Srvcs Services, Jnt
 *   Joint, Stdy Study, Lk Lake (2 each), and once each Egng Engineering, Appl
 *   Applied, Chrt Charter, Spcl Special, Cltrl Cultural, Cntrl Central,
 *   Fractnl Fractional, Hntngtn Huntington, Twnshp Township, Hght Heights, Hbr
 *   Harbor, Nth North, Cmp Campus, Priv Private, Virt Virtual, Prgs Programs;
 * - Pri Primary anywhere but before Program (8 more); a word cut off at the
 *   end of a name or of a part of one, or before a school's level: Ac, Aca and
 *   Acade Academy (25), Ele Elementary (7), Scho and Schoo School (21, but
 *   "Schoo Middle School", named for a person), Sc School after High,
 *   Elementary or Middle (4); Kind Kindergarten ending a name or before Ctr
 *   (4); Fac Facility ending a name or a part of one (3), Treat Treatment
 *   before it; Gr Greater first ("Gr Lawrence", 3) and Grade after Ninth and
 *   the like; Col College before Prep (2); Soc Just Social Justice (3); Ind
 *   Stdy Independent Study; Vis Imprd Visually Impaired; Prof Dev Professional
 *   Development; Pt Point before a name (2); Cons Consolidated also before H
 *   S, HSD, El and D (8 more); Mid Middle also before A, B, Sci, Academy,
 *   Charter and Magnet;
 * - kept in capitals: IHS, IMS and IES (International High and Middle
 *   School, Intermediate Elementary School; which one is never sure), and
 *   Texas's districts and programs by their letters (CISD, VISD, WCJJAEP).
 * Int (International or Intermediate), Med (Medicine or Medical), Spec
 * (Special or Specialty), Instr, Cnt and Corp (a company's own name) are
 * left as written: each has more than one meaning in the directory.
 *
 * A name is also shown as the directory lets it be read (NameFix, worked out
 * from the whole directory by school-names.ts): a name NCES cut off at its
 * field's width ends with the word the cut one could only be, in the whole
 * directory or in its own district's names ("Western CT Academy ...
 * Elementary Magne": "Magnet"; "Allen Village Elementary Acade", beside its
 * district's Junior and Primary Academy: "Academy"), or else with the last
 * whole word; and a
 * school whose own name is only a generic word of its level ("ELEMENTARY
 * SCHOOL") is named with its district or charter first ("Citizens of the
 * World Charter - Elementary School").
 */

import { STATES } from '../search/states.ts';

/** Capital letter runs. */
const WORD = /\p{Lu}+/gu;
const LOWER = /\p{Ll}/u;
const ONE_LETTER = /^\p{Lu}$/u;
const VOWEL = /[AEIOUYÀ-ÖØ-Ý]/u;
const APOSTROPHE = /['’`]/u;
const DIGIT = /\d/u;
const ROMAN = /^(?:X{0,3})(?:IX|IV|V?I{0,3})$/u;
/** Words, for shortenings: letters and digits; everything else separates them. */
const TOKEN = /[\p{L}\p{N}]+/gu;
const LETTER_OR_DIGIT = /[\p{L}\p{N}]/u;

/** Acronyms with a vowel, common in school names, kept in capitals. */
const ACRONYMS: ReadonlySet<string> = new Set([
  'ALC',
  'AME',
  'CTE',
  'DAEP',
  'DAR',
  'DBA',
  'ES',
  'ESD',
  'IB',
  'IDEA',
  // International High and Middle School, Intermediate Elementary School: never read out here.
  'IES',
  'IHS',
  'IMS',
  'IS',
  'ISD',
  'JJAEP',
  'KIPP',
  'NYC',
  'ROTC',
  'JROTC',
  'SDA',
  'STEAM',
  'STEM',
  'USA',
  'USD',
  'YMCA',
  'YWCA',
]);

/**
 * Texas districts and their programs by their letters, kept in capitals: CISD, VISD, GCCISD
 * (independent school districts), WCJJAEP and the like (JJAEP and DAEP programs).
 */
const ACRONYM_ENDING = /^\p{Lu}{0,4}(?:ISD|JJAEP|DAEP)$/u;

/** Short forms with no vowel that are words, not acronyms: title-cased. */
const SHORT_FORMS: ReadonlySet<string> = new Set([
  'BLVD',
  'CH',
  'CNTR',
  'CTR',
  'DR',
  'DRS',
  'FT',
  'HTRS',
  'JR',
  'KDGN',
  'LRN',
  'LRNG',
  'LTD',
  'MC',
  'MT',
  'MTN',
  'RCH',
  'RD',
  'SCH',
  'SCHL',
  'SCHS',
  'SGT',
  'SR',
  'ST',
  'STS',
  'WM',
]);

/** Lowercase after the first word. */
const SMALL_WORDS: ReadonlySet<string> = new Set([
  'AND',
  'AT',
  'FOR',
  'IN',
  'OF',
  'ON',
  'THE',
  'TO',
]);

/** Ordinal endings after a number. */
const ORDINALS: ReadonlySet<string> = new Set(['ST', 'ND', 'RD', 'TH']);

/** `text` in lowercase, character by character, keeping any character whose lowercase is longer. */
function lower(text: string): string {
  let out = '';
  for (const char of text) {
    const small = char.toLowerCase();
    out += small.length === char.length ? small : char;
  }
  return out;
}

/** First letter kept, the rest lowercase. */
function title(word: string): string {
  const first = String.fromCodePoint(word.codePointAt(0) ?? 0);
  return first + lower(word.slice(first.length));
}

function caseWord(
  word: string,
  before: string,
  after: string,
  first: boolean,
  hint: NameHint,
): string {
  if (APOSTROPHE.test(before)) return word.length <= 2 ? lower(word) : title(word);
  // The school's own state, by its code: not a word ("IN") or half of one ("CO-OP").
  if (word === hint.state && !SMALL_WORDS.has(word) && after !== '-') return word;
  if (DIGIT.test(before)) return ORDINALS.has(word) ? lower(word) : word;
  if (ONE_LETTER.test(word)) return word;
  // McKinley: the M, a lowercase c, then the rest title-cased.
  if (word.length > 3 && word.startsWith('MC')) {
    return title(word.slice(0, 2)) + title(word.slice(2));
  }
  if (ACRONYMS.has(word) || ACRONYM_ENDING.test(word) || ROMAN.test(word)) return word;
  if (SHORT_FORMS.has(word)) return title(word);
  if (!VOWEL.test(word)) return word;
  if (!first && SMALL_WORDS.has(word)) return lower(word);
  return title(word);
}

/** What is known about where a name is from. */
export interface NameHint {
  /** The USPS code of the state the school or district is in, when known. */
  readonly state?: string | null;
  /** True for a district's name. */
  readonly district?: boolean;
}

/**
 * A name in the case the page shows: title case when it is written in
 * capitals, else as written. Only the case of letters changes, so the text
 * keeps its length.
 */
export function casedName(raw: string, hint: NameHint = {}): string {
  if (LOWER.test(raw)) return raw;
  let first = true;
  return raw.replace(WORD, (word: string, at: number) => {
    const shown = caseWord(word, raw.charAt(at - 1), raw.charAt(at + word.length), first, hint);
    first = false;
    return shown;
  });
}

/** One stretch of a written name and how it is shown. */
export interface NamePiece {
  /** [from, to) in the written name. */
  readonly from: number;
  readonly to: number;
  /** The stretch as shown: the same letters in the shown case, or the words a shortening stands for. */
  readonly text: string;
  /** Whether `text` spells out a shortening. */
  readonly spelled: boolean;
}

interface Token {
  readonly text: string;
  readonly upper: string;
  readonly from: number;
  readonly to: number;
}

/** Words that mean school. */
const SCHOOL_WORDS: ReadonlySet<string> = new Set(['SCH', 'SCHL', 'SCHOOL']);
/**
 * Words before which El is Elementary: School, or another school sharing the
 * name ("Drums El/MS"). The search index reads El the same way
 * (src/search/normalize.ts).
 */
const EL_BEFORE: ReadonlySet<string> = new Set([
  ...SCHOOL_WORDS,
  'MS',
  'HS',
  'JH',
  'MIDDLE',
  'PRIMARY',
]);
/** Words El follows as a name of its own ("Beth El"). */
const EL_AS_NAME: ReadonlySet<string> = new Set(['BET', 'BETH']);
/** Marks that end a part of a name, after which El is Elementary ("Drums El/MS"). */
const PART_END = /^[-/(),;]$/u;

/** Shortenings spelled out wherever NCES writes them, in any case. */
const ALWAYS: Readonly<Record<string, string>> = {
  SCH: 'School',
  SCHL: 'School',
  SCHS: 'Schools',
  SCHLS: 'Schools',
  ELEM: 'Elementary',
  ACAD: 'Academy',
  CTR: 'Center',
  CNTR: 'Center',
  CHTR: 'Charter',
  INTRMD: 'Intermediate',
  LRNG: 'Learning',
  HTS: 'Heights',
  HGTS: 'Heights',
  TWP: 'Township',
  VOC: 'Vocational',
  EDUC: 'Education',
  EDU: 'Education',
  DIST: 'District',
  DST: 'District',
  PGM: 'Program',
  PRG: 'Program',
  PRGM: 'Program',
  PROG: 'Program',
  ALT: 'Alternative',
  COOP: 'Cooperative',
  INTL: 'International',
  ENGR: 'Engineering',
  UNIV: 'University',
  HOSP: 'Hospital',
  MTN: 'Mountain',
  INST: 'Institute',
  LRN: 'Learning',
  LRNING: 'Learning',
  DEPT: 'Department',
  DIAG: 'Diagnostic',
  CNTY: 'County',
  CHRTR: 'Charter',
  ACD: 'Academy',
  ACDY: 'Academy',
  KDGN: 'Kindergarten',
  KDG: 'Kindergarten',
  INTERMED: 'Intermediate',
  INTERM: 'Intermediate',
  RECEP: 'Reception',
  RECEPT: 'Reception',
  CONG: 'Congregation',
  TRMNT: 'Treatment',
  TRTMT: 'Treatment',
  REGNL: 'Regional',
  REGL: 'Regional',
  RGNL: 'Regional',
  COMMUN: 'Community',
  BLDG: 'Building',
  CMPS: 'Campus',
  EXCEP: 'Exceptional',
  SPECL: 'Special',
  JUV: 'Juvenile',
  JVNL: 'Juvenile',
  FACIL: 'Facility',
  MDLE: 'Middle',
  JRSR: 'Junior-Senior',
  CENTR: 'Center',
  LDRSHP: 'Leadership',
  SCI: 'Science',
  SCIS: 'Sciences',
  DEV: 'Development',
  ENV: 'Environmental',
  HMN: 'Humanities',
  EGNG: 'Engineering',
  APPL: 'Applied',
  ACADS: 'Academies',
  CHRTRS: 'Charters',
  CHRT: 'Charter',
  SRVS: 'Services',
  SRVCS: 'Services',
  SPCL: 'Special',
  BLND: 'Blind',
  IMPRD: 'Impaired',
  CLTRL: 'Cultural',
  CNTRL: 'Central',
  FRACTNL: 'Fractional',
  HNTNGTN: 'Huntington',
  TWNSHP: 'Township',
  HGHT: 'Heights',
  HBR: 'Harbor',
  JNT: 'Joint',
  NTH: 'North',
  CMP: 'Campus',
  SYS: 'System',
  PRIV: 'Private',
  VIRT: 'Virtual',
  PRGS: 'Programs',
  STDY: 'Study',
  LK: 'Lake',
};

/** Whether a word, in capitals, is a shortening the page spells out wherever it stands. */
export function isShortening(word: string): boolean {
  return ALWAYS[word] !== undefined;
}

/** Words for high school. */
const HIGH_WORDS: ReadonlySet<string> = new Set(['HIGH', 'HI', 'HS']);
/** Words Jr is Junior before, as in "Jr High" and "Jr/Sr High"; Sr is Senior before the first three. */
const GRADE_LEVEL_AFTER: ReadonlySet<string> = new Set([...HIGH_WORDS, 'SR', 'SENIOR']);
/** Words Hi is High after ("Jr Hi"). */
const HI_AFTER: ReadonlySet<string> = new Set(['JR', 'SR', 'JUNIOR', 'SENIOR']);
/** School words, as a shortening's neighbour. */
const SCHOOL_KIND: ReadonlySet<string> = new Set([
  ...SCHOOL_WORDS,
  'SCHS',
  'SCHLS',
  'SCHOOLS',
  'ELEM',
  'ELEMENTARY',
  'MIDDLE',
  'HIGH',
  'GRADE',
  'SD',
  'DIST',
  'DISTRICT',
  'ISD',
  // "Lamar Cons H S", "S and S Cons El", "Mundelein Cons HSD 120", "Marengo-Union E Cons D 165".
  'H',
  'HS',
  'HSD',
  'EL',
  'D',
]);
/** Words Cons is Consolidated after ("Dimmick Comm Cons SD"). */
const CONSOLIDATED_AFTER: ReadonlySet<string> = new Set([
  'COMM',
  'COM',
  'COMMUNITY',
  'COUNTY',
  'CO',
]);
/** Words Ed is Education after ("Sp Ed", "Alt Ed"). */
const EDUCATION_AFTER: ReadonlySet<string> = new Set([
  'SP',
  'SPEC',
  'SPECL',
  'SPECIAL',
  'ALT',
  'ALTERNATIVE',
  'ADULT',
  'COMM',
  'COM',
  'COMMUNITY',
  'CAREER',
  'VOC',
  'VOCATIONAL',
  'CONTINUING',
  'GENERAL',
  'PHYSICAL',
]);
/** Words Ed is Education before ("Ed Center"). */
const EDUCATION_BEFORE: ReadonlySet<string> = new Set([
  'CTR',
  'CNTR',
  'CENTER',
  'PROG',
  'PROGRAM',
  'PRG',
  'PGM',
  'COOP',
  'SERVICES',
]);
/** Words Sp and Spec are Special before. */
const SPECIAL_BEFORE: ReadonlySet<string> = new Set([
  'ED',
  'EDUC',
  'EDUCATION',
  'SERV',
  'SERVICES',
  'SRVS',
  'SRVCS',
]);
/** Words Mid is Middle before: "Wilmington Mid Sci Tech", "Walnut Park Mid B". */
const MIDDLE_BEFORE: ReadonlySet<string> = new Set([
  ...SCHOOL_WORDS,
  'SCHL',
  'HIGH',
  'AND',
  'A',
  'B',
  'SCI',
  'SCIENCE',
  'ACAD',
  'ACADEMY',
  'CHARTER',
  'MAGNET',
]);
/** Words Sec is Secondary before. */
const SECONDARY_BEFORE: ReadonlySet<string> = new Set([...SCHOOL_WORDS, 'CAREER', 'CENTER', 'CTR']);
/** Words that make Corr a correctional facility. */
const FACILITY_WORDS: ReadonlySet<string> = new Set([
  'C',
  'CENTER',
  'CENTR',
  'CENT',
  'CTR',
  'FACIL',
  'FACILITY',
  'INST',
  'INSTITUTION',
]);
/** Words Cent is Center after. */
const CENTER_AFTER: ReadonlySet<string> = new Set([
  'CAREER',
  'CORR',
  'CORRECTIONAL',
  'EDUCATION',
  'LEARNING',
  'TECHNICAL',
  'VOC',
  'VOCATIONAL',
]);
/** Words Mt is not Mount before: "Mt View", "Mt Valley" and a school's own words. */
const MOUNT_NOT_BEFORE: ReadonlySet<string> = new Set([
  'VIEW',
  'VALLEY',
  ...SCHOOL_WORDS,
  'SCHL',
  'SCHS',
]);
/** Words Alter is Alternative before ("Brazoria Co Alter Ed Ctr", "Venture Alter H S"). */
const ALTERNATIVE_BEFORE: ReadonlySet<string> = new Set([
  'ED',
  'EDUC',
  'EDUCATION',
  'CTR',
  'CNTR',
  'CENTER',
  'PROG',
  'PROGRAM',
  'PGM',
  'H',
  'HS',
  'SCH',
  'SCHL',
  'SCHOOL',
]);
/** Words of a school's level, which a cut-off Ac or Ele names the school before ("Learning Ac HS"). */
const LEVEL_WORDS: ReadonlySet<string> = new Set([
  ...SCHOOL_WORDS,
  'EL',
  'ELEM',
  'ELEMENTARY',
  'ES',
  'MS',
  'HS',
  'MIDDLE',
  'HIGH',
]);
/** Words Sc, at the end of a name, is School after ("Magnet High Sc"). */
const SCHOOL_AFTER: ReadonlySet<string> = new Set(['HIGH', 'ELEMENTARY', 'ELEM', 'MIDDLE']);
/** Words Kind is Kindergarten before ("Madge T. James Kind. Ctr."). */
const KINDERGARTEN_BEFORE: ReadonlySet<string> = new Set(['CTR', 'CNTR', 'CENTER']);
/** Words Treat is Treatment before ("Gentry Residential Treat. Fac."). */
const TREATMENT_BEFORE: ReadonlySet<string> = new Set([
  'FAC',
  'FACIL',
  'FACILITY',
  'CTR',
  'CNTR',
  'CENTER',
]);
/** Words Gr is Grade after ("Raymore-Peculiar Ninth Gr Cntr"). */
const ORDINAL_WORDS: ReadonlySet<string> = new Set([
  'SIXTH',
  'SEVENTH',
  'EIGHTH',
  'NINTH',
  'TENTH',
]);
/** Words Col is College before ("Col Prep"): elsewhere it is Colonel's. */
const COLLEGE_BEFORE: ReadonlySet<string> = new Set(['PREP', 'PREPARATORY']);
/** Words Pri is not Primary before: a program's own name. */
const NOT_PRIMARY_BEFORE: ReadonlySet<string> = new Set(['PROGRAM', 'PROG', 'PGM', 'PRG']);

/** Words Det is Detention after. */
const DETENTION_AFTER: ReadonlySet<string> = new Set(['JUVENILE', 'JUV', 'JVNL']);

/**
 * State codes spelled out as their states where they stand for the school's
 * own state. Left out are the codes that are also words, names, particles
 * or other shortenings (AL, CO, DE, HI, ID, IN, LA, MA, ME, MS, OH, OK, OR),
 * and DC, which names its city as often as its district.
 */
const STATE_NAMES: Readonly<Record<string, string>> = Object.fromEntries(
  STATES.filter(
    ([code]) =>
      ![
        'AL',
        'CO',
        'DC',
        'DE',
        'HI',
        'ID',
        'IN',
        'LA',
        'MA',
        'ME',
        'MS',
        'OH',
        'OK',
        'OR',
      ].includes(code),
  ),
);

/** Words after which Pub is Public. */
const PUBLIC_BEFORE: ReadonlySet<string> = new Set([
  ...SCHOOL_WORDS,
  'SCHS',
  'SCHLS',
  'SCHOOLS',
  'CHTR',
  'CHARTER',
]);
/** Words before which Comm is not Community ("Comm Arts": Communication Arts). */
const NOT_COMMUNITY_BEFORE: ReadonlySet<string> = new Set(['ARTS', 'ART']);

/** The first character after a token that is not a space, past one period; '' at the end. */
function markAfter(raw: string, token: Token): string {
  let at = token.to;
  if (raw[at] === '.') at++;
  while (at < raw.length && /\s/u.test(raw[at] ?? '')) at++;
  return raw[at] ?? '';
}

/** What a word stands for, when it is a shortening here, else null. */
function spellOut(raw: string, tokens: readonly Token[], i: number, hint: NameHint): string | null {
  const token = tokens[i];
  if (token === undefined) return null;
  const { upper } = token;
  // A district's "Pub Sch" is its Public Schools.
  if (hint.district === true && upper === 'SCH' && tokens[i - 1]?.upper === 'PUB') return 'Schools';
  const always = ALWAYS[upper];
  if (always !== undefined) return always;
  const capitals = token.text === upper;
  const first = i === 0;
  const next = tokens[i + 1];
  const last = next === undefined;
  const before = tokens[i - 1];
  // "PS 15", "MS 45", "JHS 22": a numbered school keeps its letters.
  const numbered =
    next !== undefined && /^\d/u.test(next.text) && /^\s+$/u.test(raw.slice(token.to, next.from));
  const after = next?.upper ?? '';
  const previous = before?.upper ?? '';
  // The school's own state by its code, where casedName keeps it as the state.
  if (
    capitals &&
    upper === hint.state &&
    !SMALL_WORDS.has(upper) &&
    raw[token.to] !== '-' &&
    STATE_NAMES[upper] !== undefined
  ) {
    return STATE_NAMES[upper];
  }
  switch (upper) {
    case 'EL': {
      if (first || (before !== undefined && EL_AS_NAME.has(before.upper))) return null;
      if (last || PART_END.test(markAfter(raw, token))) return 'Elementary';
      return EL_BEFORE.has(next.upper) ? 'Elementary' : null;
    }
    case 'ES':
      return capitals && !first ? 'Elementary School' : null;
    case 'HS':
      return capitals && !numbered ? 'High School' : null;
    case 'MS':
      return capitals && !numbered && hint.state !== 'MS' && !SCHOOL_WORDS.has(next?.upper ?? '')
        ? 'Middle School'
        : null;
    case 'JHS':
      return capitals && !numbered ? 'Junior High School' : null;
    case 'JH':
      return capitals && !first ? 'Junior High' : null;
    case 'SHS':
      // "J-SHS" is a shortening of its own.
      return capitals && !first && /\s/u.test(raw[token.from - 1] ?? '')
        ? 'Senior High School'
        : null;
    case 'JSHS':
      return capitals && !first ? 'Junior-Senior High School' : null;
    case 'CS':
      return capitals && !first && !numbered ? 'Charter School' : null;
    case 'PCS':
      return capitals && !first ? 'Public Charter School' : null;
    case 'INT':
      return capitals && last && raw[token.to] !== "'" && !first ? 'Intermediate' : null;
    case 'PRI':
      // "Curtisville Pri Ctr", "Basis San Antonio Pri - Northeast Campus", "Pri DAEP" (beside
      // its district's "Secondary DAEP").
      return NOT_PRIMARY_BEFORE.has(after) ? null : 'Primary';
    case 'PUB':
      return !last && PUBLIC_BEFORE.has(next.upper) ? 'Public' : null;
    case 'COM':
    case 'COMM':
      // Not the end of a web address ("School.com").
      if (raw[token.from - 1] === '.') return null;
      return last || !NOT_COMMUNITY_BEFORE.has(next.upper) ? 'Community' : null;
    case 'CO':
      // "Co-op" and "Co/..." are words of their own.
      return !first && !last && /^[.\s]/u.test(raw.slice(token.to)) ? 'County' : null;
    case 'SD':
      return capitals && !first ? 'School District' : null;
    case 'MT':
      // "Mt View" and "Mt Valley" are as often Mountain's; a Montana school's MT is its state.
      return !last && /^\p{L}/u.test(next.text) && !MOUNT_NOT_BEFORE.has(after) ? 'Mount' : null;
    case 'BLVD':
      return first ? null : 'Boulevard';
    case 'RD':
      // Not an ordinal's ending ("63RD").
      return !first && /\s/u.test(raw[token.from - 1] ?? '') ? 'Road' : null;
    case 'CTY':
      return first ? null : 'County';
    case 'ALTER':
      // "Archbishop Alter High School" is named for a man.
      return (!first && last) || ALTERNATIVE_BEFORE.has(after) ? 'Alternative' : null;
    case 'JR':
      // "Martin Luther King Jr High" is named for a man, not a grade.
      return GRADE_LEVEL_AFTER.has(after) && previous !== 'KING' ? 'Junior' : null;
    case 'SR':
      return HIGH_WORDS.has(after) && previous !== 'KING' ? 'Senior' : null;
    case 'HI':
      return HI_AFTER.has(previous) || SCHOOL_WORDS.has(after) ? 'High' : null;
    case 'FT':
      return !last && /^\p{L}/u.test(next.text) ? 'Fort' : null;
    case 'WM':
      return !last && /^\p{L}/u.test(next.text) ? 'William' : null;
    case 'CONS':
      return SCHOOL_KIND.has(after) || CONSOLIDATED_AFTER.has(previous) ? 'Consolidated' : null;
    case 'AVE':
      return first ? null : 'Avenue';
    case 'REG':
      return first || last ? null : 'Regional';
    case 'ED':
      return EDUCATION_AFTER.has(previous) || (!first && EDUCATION_BEFORE.has(after))
        ? 'Education'
        : null;
    case 'SP':
    case 'SPEC':
      return SPECIAL_BEFORE.has(after) ? 'Special' : null;
    case 'SERV':
      return ['SPECIAL', 'SPEC', 'SPECL'].includes(previous) ? 'Services' : null;
    case 'PERF':
      return after === 'ARTS' || after === 'ART' ? 'Performing' : null;
    case 'MID':
      return !first && (last || MIDDLE_BEFORE.has(after)) ? 'Middle' : null;
    case 'SEC':
      return !first && (last || SECONDARY_BEFORE.has(after)) ? 'Secondary' : null;
    case 'CORR':
      return !first && FACILITY_WORDS.has(after) ? 'Correctional' : null;
    case 'DET':
      return DETENTION_AFTER.has(previous) ? 'Detention' : null;
    case 'SEV':
      return after === 'DISABLED' ? 'Severely' : null;
    case 'CENT':
      // "Vocational Cent", "Corr Cent/Acad"; never Central's start ("Cent Elem" is not written so).
      return last || CENTER_AFTER.has(previous) ? 'Center' : null;
    // A word cut off where a part of the name ends, or before a school's level: "Leadership Ac",
    // "Christian Aca", "Arts Acade (90334)", "Learning Ac HS", "Riverchase Ele", "Christian Scho".
    case 'AC':
    case 'ACA':
    case 'ACADE':
      return !first && (last || PART_END.test(markAfter(raw, token)) || LEVEL_WORDS.has(after))
        ? 'Academy'
        : null;
    case 'ELE':
      return first ? null : 'Elementary';
    case 'SCHO':
    case 'SCHOO':
      // "Schoo Middle School" is named for a person.
      return first ? null : 'School';
    case 'SC':
      // "Magnet High Sc"; SC is South Carolina's in its own schools' names.
      return last && hint.state !== 'SC' && SCHOOL_AFTER.has(previous) ? 'School' : null;
    case 'KIND':
      return !first && (last || KINDERGARTEN_BEFORE.has(after)) ? 'Kindergarten' : null;
    case 'FAC':
      // "Juvenile Detention Fac"; "FAC Christian School" is a name.
      return !first && (last || PART_END.test(markAfter(raw, token))) ? 'Facility' : null;
    case 'TREAT':
      return TREATMENT_BEFORE.has(after) ? 'Treatment' : null;
    case 'GR':
      // "Gr Lawrence Regional Vocational Technical", "Ninth Gr Cntr"; "Gr 9-12" says no more.
      if (ORDINAL_WORDS.has(previous)) return 'Grade';
      return first && !last && /^\p{L}{2,}/u.test(next.text) ? 'Greater' : null;
    case 'COL':
      return COLLEGE_BEFORE.has(after) ? 'College' : null;
    case 'SOC':
      return after === 'JUST' ? 'Social' : null;
    case 'JUST':
      return previous === 'SOC' ? 'Justice' : null;
    case 'IND':
      return after === 'STDY' || after === 'STUDY' ? 'Independent' : null;
    case 'VIS':
      return after === 'IMPRD' || after === 'IMPAIRED' ? 'Visually' : null;
    case 'PROF':
      return after === 'DEV' || after === 'DEVELOPMENT' ? 'Professional' : null;
    case 'PT':
      return !last && /^\p{L}/u.test(next.text) ? 'Point' : null;
    default:
      return null;
  }
}

/**
 * Where tokens i and i + 1 are "H S" or "H.S." after the start of a name,
 * High School; else null.
 */
function highSchool(raw: string, tokens: readonly Token[], i: number): string | null {
  const h = tokens[i];
  const s = tokens[i + 1];
  if (i === 0 || h?.text !== 'H' || s?.text !== 'S') return null;
  return /^[ .]$/u.test(raw.slice(h.to, s.from)) ? 'High School' : null;
}

/**
 * How the directory lets a school's or district's name be read, worked out
 * from the whole directory (school-names.ts).
 */
export interface NameFix {
  /**
   * Where the written name stops being shown: from here on it is a word NCES
   * cut off where its field ends, with any mark or joining word hanging
   * before it.
   */
  readonly end?: number;
  /** Shown in place of what is left off: the one word the cut-off word can be the start of. */
  readonly word?: string;
  /**
   * The school's district or charter, as shown, named first: the school's
   * own name is only generic words ("Elementary School").
   */
  readonly district?: string;
}

/** Between a district named first and the school's own name. */
export const DISTRICT_MARK = ' - ';

/**
 * A name cut into the stretches the page shows it as: the written text in its
 * shown case, and each shortening spelled out. The pieces cover the written
 * name in order; with a fix, a district named first comes before them all,
 * and what the fix leaves off is one last piece.
 */
export function nameLayout(raw: string, hint: NameHint = {}, fix: NameFix = {}): NamePiece[] {
  const cased = casedName(raw, hint);
  const limit = Math.min(raw.length, Math.max(0, fix.end ?? raw.length));
  const tokens: Token[] = [];
  for (const match of raw.slice(0, limit).matchAll(TOKEN)) {
    const from = match.index;
    tokens.push({
      text: match[0],
      upper: match[0].toUpperCase(),
      from,
      to: from + match[0].length,
    });
  }
  const pieces: NamePiece[] = [];
  let at = 0;
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    if (token === undefined) break;
    // A shortening of two words ("H S") ends at the second.
    const pair = highSchool(raw, tokens, i);
    const words = pair ?? spellOut(raw, tokens, i, hint);
    if (words === null) continue;
    const end = (pair === null ? token : tokens[++i]) ?? token;
    // "ELEM." is "Elementary": the period goes with the shortening, unless a word follows it at once.
    const to = Math.min(
      limit,
      raw[end.to] === '.' && !LETTER_OR_DIGIT.test(raw[end.to + 1] ?? '') ? end.to + 1 : end.to,
    );
    if (token.from > at) {
      pieces.push({ from: at, to: token.from, text: cased.slice(at, token.from), spelled: false });
    }
    pieces.push({ from: token.from, to, text: words, spelled: true });
    at = to;
  }
  if (at < limit) {
    pieces.push({ from: at, to: limit, text: cased.slice(at, limit), spelled: false });
  }
  if (limit < raw.length) {
    pieces.push({ from: limit, to: raw.length, text: fix.word ?? '', spelled: true });
  }
  if (fix.district !== undefined && fix.district !== '') {
    pieces.unshift({ from: 0, to: 0, text: `${fix.district}${DISTRICT_MARK}`, spelled: true });
  }
  return pieces;
}

/**
 * A school or district name as the page shows it, with any run of spaces NCES
 * left in it ("M. L. King  Elementary") shown as one, and the directory's fix
 * for it, if it has one.
 */
export function displayName(raw: string, hint: NameHint = {}, fix: NameFix = {}): string {
  return nameLayout(raw, hint, fix)
    .map((piece) => piece.text)
    .join('')
    .replace(/\s{2,}/gu, ' ')
    .trim();
}

/**
 * Ranges of a written name ([start, end), such as the parts a search matched)
 * as ranges of the shown name. Within a spelled-out shortening, a match of
 * its first letters marks the same letters of the words when they start the
 * same way ("Sc" of "Sch" is "Sc" of "School"), and the whole words otherwise.
 */
export function shownRanges(
  layout: readonly NamePiece[],
  raw: string,
  ranges: readonly (readonly [number, number])[],
): [number, number][] {
  const out: [number, number][] = [];
  for (const [start, end] of ranges) {
    let shownAt = 0;
    for (const piece of layout) {
      const from = Math.max(start, piece.from);
      const to = Math.min(end, piece.to);
      if (to > from) {
        if (!piece.spelled) {
          out.push([shownAt + from - piece.from, shownAt + to - piece.from]);
        } else {
          const written = raw.slice(piece.from, piece.to).replace(/\.$/u, '');
          const prefix =
            from === piece.from &&
            to - from < written.length &&
            piece.text.toUpperCase().startsWith(written.toUpperCase());
          out.push([shownAt, shownAt + (prefix ? to - from : piece.text.length)]);
        }
      }
      shownAt += piece.text.length;
    }
  }
  out.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const merged: [number, number][] = [];
  // A match in what a fix left off shows nowhere.
  for (const range of out.filter(([start, end]) => end > start)) {
    const previous = merged[merged.length - 1];
    if (previous !== undefined && range[0] <= previous[1]) {
      previous[1] = Math.max(previous[1], range[1]);
    } else merged.push([range[0], range[1]]);
  }
  return merged;
}
