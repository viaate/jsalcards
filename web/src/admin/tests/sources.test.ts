import { gzipSync } from 'node:zlib';
import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';

import { decodeDay, type StoredDay } from '../sources';

// SYNTHETIC: one stored day as the API sends it.
const SUMMARY = JSON.stringify({
  v: 1,
  closings: [
    {
      nces: 'SYN0000001',
      status: 0,
      reason: 0,
      level: 'district',
      source: 'synthetic-station-a',
      type: 'broadcaster_list',
      lo: null,
      hi: '2026-11-17T17:55:00+00:00',
      row_stamp: null,
      present: true,
      posted_by: 'synthetic-station-a',
      contributing: [['synthetic-station-a', 'broadcaster_list']],
    },
  ],
  links: { 'synthetic-station-a': 'https://example.test/closings' },
});

function stored(text: string, sha = createHash('sha256').update(text).digest('hex')): StoredDay {
  const packed = Buffer.from(gzipSync(Buffer.from(text)));
  return {
    day: '2026-11-17',
    sha256: sha,
    closings: 1,
    published_at: '2026-11-17T18:00:05+00:00',
    written_at: '2026-11-17T18:00:30+00:00',
    mode: 'on',
    latest_at: null,
    // two parts, cut mid-stream, as the reader cuts large days
    parts: [packed.subarray(0, 20), packed.subarray(20)].map((p) =>
      Buffer.from(p).toString('base64'),
    ),
  };
}

describe('the admin sources decoder', () => {
  it('joins the parts, unzips them and keeps the rows and links', async () => {
    const day = await decodeDay(stored(SUMMARY));
    expect(day.rows?.[0]?.source).toBe('synthetic-station-a');
    expect(day.links['synthetic-station-a']).toBe('https://example.test/closings');
    expect(day.publishedAt).toBe('2026-11-17T18:00:05+00:00');
    expect(day.shadow).toBe(false);
    expect(day.latestAt).toBeNull();
  });

  it('marks a shadow publish and a later publish that left these sources', async () => {
    const day = await decodeDay({
      ...stored(SUMMARY),
      mode: 'shadow',
      latest_at: '2026-11-17T18:30:00+00:00',
    });
    expect(day.shadow).toBe(true);
    expect(day.latestAt).toBe('2026-11-17T18:30:00+00:00');
    expect(day.rows?.length).toBe(1);
  });

  it('shows no rows when the parts do not match their sha256 (never a mixed day)', async () => {
    const mixed = await decodeDay(stored(SUMMARY, '0'.repeat(64)));
    expect(mixed.rows).toBeNull();
    expect(mixed.writing).toBe(true);
    // parts that do not unzip (a missing or broken part) are not "being written"
    const broken = await decodeDay({ ...stored(SUMMARY), parts: ['bm90IGd6aXA='] });
    expect(broken.rows).toBeNull();
    expect(broken.writing).toBe(false);
    const missing = await decodeDay({ ...stored(SUMMARY), parts: [] });
    expect(missing.rows).toBeNull();
    expect(missing.writing).toBe(false);
  });
});
