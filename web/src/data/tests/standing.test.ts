import { describe, expect, it } from 'vitest';
import { createDataFiles } from '../files';
import type { Fetch } from '../files';
import {
  STANDING_RETRY_MS,
  awaitStanding,
  heldStanding,
  prefetchStanding,
  readStanding,
  standingUrl,
  triedStanding,
} from '../standing';
import type { PredictionsFile } from '../../types/generated';

const STAMP = '7c4cc6e710a6';
const BODY = {
  schema_version: 1,
  stamp: STAMP,
  directory: { generated_on: '2026-10-24', schools: 3, districts: 1 },
  winter: [null],
  flags: [0],
  usual: { advisory: [null], warning: [null] },
  levels: {},
  ref: {},
  record: {},
};

function files() {
  return createDataFiles(['predictions/latest.json'], 'https://example.test/data/');
}

/** A fetch that answers each call in turn (a status, or a throw), and counts its calls. */
function answers(...said: (number | 'throw')[]): { fetch: Fetch; urls: string[] } {
  const urls: string[] = [];
  const fetch: Fetch = (url) => {
    urls.push(url);
    const next = said[Math.min(urls.length - 1, said.length - 1)];
    if (next === 'throw') return Promise.reject(new TypeError('closed'));
    return Promise.resolve(new Response(JSON.stringify(BODY), { status: next ?? 200 }));
  };
  return { fetch, urls };
}

describe('the standing file', () => {
  it('is beside predictions/latest.json on the same root, by a stamp of 12 hex digits', () => {
    const here = files();
    expect(standingUrl(here, STAMP)).toBe(
      'https://example.test/data/predictions/standing/7c4cc6e710a6.json',
    );
    expect(standingUrl(here, 'ABC')).toBeNull();
  });

  it('is read once per stamp and kept, a second ask joining the first', async () => {
    const here = files();
    const { fetch, urls } = answers(200);
    const first = readStanding(here, STAMP, fetch);
    // A panel opened while it is on its way (a prefetch's) waits for that same read.
    expect(awaitStanding(here, STAMP)).toBe(true);
    expect(triedStanding(here, STAMP)).toBe(true);
    await first;
    expect(awaitStanding(here, STAMP)).toBe(false);
    const [a, b] = await Promise.all([
      readStanding(here, STAMP, fetch),
      readStanding(here, STAMP, fetch),
    ]);
    expect(a?.stamp).toBe(STAMP);
    expect(b).toBe(a);
    expect(await readStanding(here, STAMP, fetch)).toBe(a);
    expect(urls).toHaveLength(1);
    expect(heldStanding(here, STAMP)).toBe(a);
    expect(a).toBe(await first);
    expect(triedStanding(here, STAMP)).toBe(true);
  });

  it('is asked for once more a minute after a failed read, and then no more', async () => {
    const here = files();
    let clock = 1_000_000;
    const now = () => clock;
    const { fetch, urls } = answers(404, 'throw', 200);
    expect(await readStanding(here, STAMP, fetch, now)).toBeNull();
    expect(triedStanding(here, STAMP, clock)).toBe(true);
    clock += STANDING_RETRY_MS - 1;
    expect(await readStanding(here, STAMP, fetch, now)).toBeNull();
    expect(urls).toHaveLength(1);
    clock += 1;
    expect(triedStanding(here, STAMP, clock)).toBe(false);
    expect(await readStanding(here, STAMP, fetch, now)).toBeNull();
    expect(urls).toHaveLength(2);
    clock += 10 * STANDING_RETRY_MS;
    expect(await readStanding(here, STAMP, fetch, now)).toBeNull();
    expect(urls).toHaveLength(2);
    expect(triedStanding(here, STAMP, clock)).toBe(true);
  });

  it('a file that is not the stamp’s is no file', async () => {
    const here = files();
    const { fetch } = answers(200);
    expect(await readStanding(here, '0123456789ab', fetch)).toBeNull();
  });

  it('is started when a predictions file names it with a storm-class day, before any panel opens', () => {
    const here = files();
    const asked: (() => void)[] = [];
    const later = (run: () => void) => asked.push(run);
    const day = (kind: string) => ({ why: { base: { kind } } });
    const file = (kind: string, standing: string | null = STAMP) =>
      ({
        standing,
        districts: [{ days: [day('pooled'), day(kind)] }],
        outlooks: [],
      }) as unknown as PredictionsFile;
    prefetchStanding(here, file('pooled'), later);
    prefetchStanding(here, file('class', null), later);
    expect(asked).toHaveLength(0);
    prefetchStanding(here, file('class'), later);
    expect(asked).toHaveLength(1);
    const school = {
      standing: STAMP,
      districts: [],
      outlooks: [day('class')],
    } as unknown as PredictionsFile;
    prefetchStanding(files(), school, later);
    expect(asked).toHaveLength(2);
  });
});
