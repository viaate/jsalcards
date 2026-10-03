/** District names as a family says them: their own words, the kind and the state's ids left out. */

/** Words before a district's kind that only say what kind of district it is. */
const KIND_WORDS = [
  'community unit',
  'community consolidated',
  'community high',
  'township high',
  'regional high',
  'unified union',
  'union free',
  'exempted village',
  'joint union high',
  'joint union elementary',
  'union high',
  'union elementary',
  'reorganized',
  'common',
  'unified',
  'independent',
  'consolidated',
  'community',
  'area',
  'public',
  'local',
  'joint',
  'unit',
  'high',
  'middle',
  'grade',
  'elementary',
  // "Township" only as Illinois writes "Township High School District": "Township HSD".
  'township(?=\\s+(?:hsd|h\\.s\\.d\\.?|chsd)\\b)',
].join('|');
/** What a district is called as a district: "School District", "CUSD". */
const KIND_NOUNS = [
  'school district',
  'school dist',
  'school corp(?:oration)?',
  'schl corp',
  'school system',
  // Not "School": a district of one school is its name.
  'schools',
  'district',
  'dist',
  'cusd',
  'cud',
  'ccsd',
  'chsd',
  'cuhsd',
  'uhsd',
  'jusd',
  'cesd',
  'hsd',
  'esd',
  'psd',
  'gsd',
  'chd',
  'msd',
  'usd',
  'isd',
  'cisd',
  'ufsd',
  'csd',
  'sd',
].join('|');
/** What can end a district's name with no noun after it: "Union High", "Unified". */
const KIND_ENDINGS = [
  '(?:joint\\s+)?union\\s+high\\s+school',
  'joint union high',
  'joint union elementary',
  'union high',
  'union elementary',
  'union free',
  'exempted village',
  'joint unified',
  'unified',
  'independent',
  'community',
  'consolidated',
  'local',
  'area',
  'joint',
].join('|');
/** A name's last kind: "Community Unit School District", "Union High", "ISD". */
const KIND = new RegExp(
  `(?:^|\\s+)(?:(?:${KIND_WORDS})\\s+)*(?:${KIND_NOUNS}|${KIND_ENDINGS})$`,
  'i',
);
/** A district's number: "204", "No. 196", "#1", "Re-1J", "127-5", "6-J", "R- 5", "10Jt-R". */
const NUMBER_TEXT = '(?:[a-z]{1,2}-?\\s?)?\\d+[a-z]{0,2}(?:-[a-z\\d]{1,2})*';
/** A district's number after its kind, and "Jt." (joint) after it. */
const NUMBER = new RegExp(
  `\\s+(?:re:\\s*)?(?:no?\\.?\\s*|#\\s*)?(${NUMBER_TEXT})(?:\\s+jt\\.?)?$`,
  'i',
);
/** A name that leads with its kind and number, then its place: "School District No. Re-2 Brush". */
const LEADING = new RegExp(
  `^(?:(?:${KIND_WORDS})\\s+)*(?:school district|district)\\s+(?:no?\\.?\\s*|#\\s*)?(${NUMBER_TEXT})(?:\\s+(.+))?$`,
  'i',
);
/** Colorado's "in the county of El Paso and State of Colorado", cut short or not. */
const COUNTY_TAIL =
  /(?<=\d[a-z\d-]*(?:\s+jt\.?)?)\s+(?:in|of)\s+(?:the\s+)?co(?:u(?:n(?:ty?|ties)?)?)?\b.*$/i;
/** The county a Colorado name says, in its capitalized words: "Denver", "El Paso". */
const COUNTY = /\bcount(?:y|ies)\s+of\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)/;
/** Arizona's id after a name: " (4192)". */
const STATE_ID = /\s*\(\d+\)$/;
/** A name with nothing left but kinds. */
const KIND_ONLY = new RegExp(
  `^(?:(?:${KIND_WORDS}|${KIND_NOUNS}|township|regional|high|elementary|unit|union)(?:\\s+|$))+$`,
  'i',
);

/** `words` null for a name of nothing but its kind and number (CUSD 300); `whole` keeps the kind. */
export interface DistrictName {
  readonly words: string | null;
  readonly number: string | null;
  readonly whole: string;
}

/** A word that names no place alone: "Central Local" stays whole, never "Central". */
const PLACELESS =
  /^(?:north|south|east|west|northern|southern|eastern|western|northeast|northwest|southeast|southwest|central|united|union|valley|county|city|community)$/i;

/** Its words and number; the whole name where its words alone would say no place. */
function parts(words: string | null, number: string | null, whole: string): DistrictName {
  if (words === null || words.replace(/[^a-z]/gi, '').length < 3 || KIND_ONLY.test(words)) {
    return { words: number === null ? whole : null, number, whole };
  }
  if (!PLACELESS.test(words)) return { words, number, whole };
  return { words: number === null ? whole : `${words} ${number}`, number: null, whole };
}

/** A district's name apart: "Indian Prairie" and "204" for Indian Prairie CUSD 204. */
export function districtName(shown: string): DistrictName {
  let name = shown
    .replace(STATE_ID, '')
    // A name run into its kind: "GreeleySchool District No. 6".
    .replace(/([a-z])(School District)/g, '$1 $2');
  const county = COUNTY.exec(name)?.[1] ?? null;
  name = name.replace(COUNTY_TAIL, '').trim();
  const whole = name;
  const leading = LEADING.exec(name);
  if (leading !== null) return parts(leading[2]?.trim() ?? county, leading[1] ?? null, whole);
  let number: string | null = null;
  const numbered = NUMBER.exec(name);
  if (numbered !== null && KIND.test(name.slice(0, numbered.index))) {
    number = numbered[1] ?? null;
    name = name.slice(0, numbered.index);
  }
  let cut = false;
  for (let kind = KIND.exec(name); kind !== null; kind = KIND.exec(name)) {
    name = name.slice(0, kind.index);
    cut = true;
  }
  return cut ? parts(name.trim(), number, whole) : { words: whole, number: null, whole };
}

/** Districts whose words another district of the state shares (Hinsdale 86, Hinsdale 181): they keep their numbers. */
export function alikeDistricts(
  districts: readonly {
    readonly id: string;
    readonly state: string | null;
    readonly shown: string;
  }[],
): string[] {
  const byName = new Map<string, string[]>();
  for (const { id, state, shown } of districts) {
    const { words } = districtName(shown);
    if (words === null) continue;
    const key = `${state ?? ''}\n${words.toLowerCase()}`;
    const ids = byName.get(key);
    if (ids === undefined) byName.set(key, [id]);
    else ids.push(id);
  }
  return [...byName.values()].filter((ids) => ids.length > 1).flat();
}
