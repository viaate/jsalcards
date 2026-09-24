import { describe, expect, it } from 'vitest';

import { copy } from '../src/copy';

/** Every string leaf in the copy tree, keyed by its dotted path. */
function leaves(node: unknown, path = 'copy'): [string, string][] {
  if (typeof node === 'string') return [[path, node]];
  if (typeof node !== 'object' || node === null) {
    throw new TypeError(`${path} must be a string or a group of strings`);
  }
  return Object.entries(node).flatMap(([key, value]) => leaves(value, `${path}.${key}`));
}

const strings = leaves(copy);

const BANNED = [
  'may',
  'might',
  'estimate',
  'estimated',
  'estimates',
  'approximate',
  'approximately',
  'disclaimer',
  'beta',
  'source',
  'sources',
  'data provided',
  'powered by',
  'ai',
  'algorithm',
  'algorithms',
  'sorry',
  'please note',
  'accuracy',
];

/** Words allowed to keep a capital letter after the first word. */
const PROPER_NOUNS = new Set(['Snowlight', 'ZIP', 'US']);

describe('copy', () => {
  it('holds the seeded strings', () => {
    expect(copy.search.placeholder).toBe('Search a school, city, or ZIP');
    expect(copy.status).toEqual({
      closed: 'Closed',
      delayed: 'Delayed',
      remote: 'Remote',
      earlyDismissal: 'Early dismissal',
    });
    expect(copy.empty).toEqual({
      noClosures: 'No weather closures today',
      notEnoughData: 'Not enough data yet',
      noThreat: 'No weather threat in the forecast',
    });
    expect(copy.actions).toEqual({
      replay: 'Replay a past storm',
      pin: 'Pin as my school',
      share: 'Share',
    });
    expect(copy.days).toEqual({ today: 'Today', tomorrow: 'Tomorrow' });
    expect(copy.nav).toEqual({
      live: 'Live',
      listView: 'List view',
      seasonStats: 'Season stats',
      trackRecord: 'Track record',
      about: 'About',
    });
    expect(copy.appName).toBe('Snowlight');
  });

  it('is frozen all the way down', () => {
    const groups: unknown[] = [copy];
    while (groups.length > 0) {
      const group = groups.pop();
      if (typeof group !== 'object' || group === null) continue;
      expect(Object.isFrozen(group)).toBe(true);
      groups.push(...Object.values(group as Record<string, unknown>));
    }
    expect(() => {
      (copy.status as { closed: string }).closed = 'Open';
    }).toThrow(TypeError);
    expect(copy.status.closed).toBe('Closed');
  });

  it.each(strings)('%s uses none of the banned words', (_path, text) => {
    const lower = text.toLowerCase();
    for (const phrase of BANNED) {
      const pattern = new RegExp(`\\b${phrase.replace(/ /g, '\\s+')}\\b`, 'u');
      expect(pattern.test(lower), `"${text}" contains "${phrase}"`).toBe(false);
    }
  });

  it.each(strings)('%s has no exclamation marks, emoji or em dashes', (_path, text) => {
    expect(text).not.toMatch(/!/u);
    expect(text).not.toMatch(/\u2014/u);
    expect(text).not.toMatch(/\p{Extended_Pictographic}/u);
  });

  it.each(strings)('%s is trimmed sentence case', (_path, text) => {
    expect(text).toBe(text.trim());
    expect(text).not.toMatch(/\s{2,}/u);
    expect(text).toMatch(/^[\p{Lu}\p{N}]/u);
    const rest = text.split(/\s+/u).slice(1);
    for (const word of rest) {
      const bare = word.replace(/[^\p{L}\p{N}-]/gu, '');
      if (/^\p{Lu}/u.test(bare)) {
        expect(PROPER_NOUNS.has(bare), `"${word}" in "${text}" breaks sentence case`).toBe(true);
      }
    }
  });
});
