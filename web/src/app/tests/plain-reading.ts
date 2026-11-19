/**
 * The reading test of the plain why (WHY-PLAIN 5), for the tests alone: Flesch-Kincaid grade by
 * fixed rules, the longest sentence, and the banned words. Words split on spaces and en dashes;
 * a token with a digit is one word of 2 syllables; a district or school name is one word of 2
 * syllables; every other word by `syllables`; sentences end at "." or "?" followed by a space or
 * the end. A string of 3 words or fewer is a label: no grade.
 */

/** Words a 12-year-old or a parent would need explained, banned from every panel string. */
export const BANNED = [
  'exposure',
  'weigh',
  'weighs',
  'weighed',
  'weighing',
  'weight',
  'weighted',
  'rank',
  'ranks',
  'ranked',
  'ranking',
  'median',
  'middle',
  'corrected',
  'correction',
  'archive',
  'class',
  'classes',
  'standing',
  'stage',
  'stages',
  'held',
  'clamp',
  'clamped',
  'floor',
  'floored',
  'factor',
  'baseline',
  'probability',
  'point',
  'points',
  'deciding',
  'scope',
  'pooled',
  'pool',
  'zone',
  'by itself',
  'county mix',
  'mix',
  'mixed',
  'prior',
  'posterior',
  'level',
  'levels',
  'shrink',
  'shrunk',
  'bound',
  'bounded',
  'cap',
  'capped',
  'odds',
  'log',
  'logit',
  'sigmoid',
  'quadrature',
  'shapley',
  'eligible',
  'situation',
  'label',
  'labeled',
  'labels',
  'fit',
  'fitted',
  'model',
  'alpha',
  'tau',
  'offset',
  'slope',
  'term',
  'parameter',
  'statistic',
  'statistics',
  'share',
  'rate',
  'rates',
  'recorded',
  'record',
  'records',
  'snapshot',
  'window',
  'deployed',
  'unit',
  'cell',
  'thin',
  'borrowed',
  'read live',
  'per',
  'net',
  'sum',
  'rounded',
  'rounding',
  'adjust',
  'adjusted',
  'adjustment',
  'estimate',
  'versus',
  'vs',
  'index',
  'threshold',
  'trace',
  'exceed',
  'exceeds',
  'aggregate',
  'cumulative',
  'historical',
  'calibrated',
  'residual',
  'variable',
  'input',
  'inputs',
  'metric',
  'region',
  'regional',
  'exposed',
  'percentile',
  'average',
  'averages',
  'balance',
  'reach',
  'reaches',
  'counted over',
  'step',
  'steps',
  'stand-in',
  'snow day',
  'snow days',
  'alone',
  'would stay at',
  'counts for',
  'main schools',
  'each counts',
  'F',
  'percent',
  'chance of rain',
  'likelihood',
  'forecasted',
  'exposures',
  'typical winter',
] as const;

export function bannedIn(text: string): string[] {
  const lower = text.toLowerCase().replaceAll('’', "'");
  return BANNED.filter((word) => {
    if (word === 'F') return /\d\s*F\b/u.test(text);
    return new RegExp(`(?<![\\p{L}-])${word.replace(/ /g, '\\s+')}(?![\\p{L}-])`, 'u').test(lower);
  });
}

export function syllables(word: string): number {
  let w = word.toLowerCase().replace(/[^a-z]/g, '');
  if (w.length === 0) return 0;
  if (w.length <= 3) return 1;
  w = w.replace(/(?:[^laeiouy]es|[^laeiouy]ed|[^laeiouy]e)$/, '').replace(/^y/, '');
  const found = w.match(/[aeiouy]{1,2}/g);
  return Math.max(1, found === null ? 1 : found.length);
}

export interface Measure {
  /** Null for a label of 3 words or fewer. */
  readonly grade: number | null;
  readonly longest: number;
}

export function measure(text: string, names: readonly string[]): Measure {
  let named = text.replaceAll(' ', ' ');
  for (const name of [...names].sort((a, b) => b.length - a.length)) {
    named = named.replaceAll(name, 'Nameword');
  }
  const sentences = named.split(/(?<=[.?])\s+/u).filter((s) => s.trim().length > 0);
  let words = 0;
  let syl = 0;
  let longest = 0;
  for (const sentence of sentences) {
    const found = sentence.split(/[\s–]+/u).filter((w) => /[\p{L}\p{N}]/u.test(w));
    longest = Math.max(longest, found.length);
    for (const w of found) {
      words += 1;
      syl +=
        /\d/.test(w) || w.startsWith('Nameword')
          ? 2
          : w.split('-').reduce((sum, part) => sum + syllables(part), 0);
    }
  }
  if (words <= 3) return { grade: null, longest };
  const grade = 0.39 * (words / sentences.length) + 11.8 * (syl / words) - 15.59;
  return { grade: Math.round(grade * 10) / 10, longest };
}
