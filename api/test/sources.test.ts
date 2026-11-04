/** GET /v1/admin/sources: the live reader's lit-closing sources, for the admin only. SYNTHETIC rows. */

import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { after, before, describe, it } from 'node:test';
import { gunzipSync, gzipSync } from 'node:zlib';
import { ADMIN_KEY, fakeKey, startApi, type Api } from './harness.ts';

let api: Api;
before(async () => {
  api = await startApi();
});
after(async () => {
  await api.close();
});

const SUMMARY = JSON.stringify({
  v: 1,
  closings: [{ nces: 'SYN0000001', source: 'synthetic-station-a', type: 'broadcaster_list' }],
  links: { 'synthetic-station-a': 'https://example.test/closings' },
});

async function seed(): Promise<void> {
  const packed = Buffer.from(gzipSync(Buffer.from(SUMMARY))).toString('base64');
  const sha = createHash('sha256').update(SUMMARY).digest('hex');
  await api.sql(
    `INSERT INTO lit_sources_head
       (day, sha256, parts, closings, published_at, written_at, mode, latest_at)
     VALUES ('2026-11-17', ?1, 1, 1, '2026-11-17T18:00:05+00:00', '2026-11-17T18:00:30+00:00',
       'shadow', '2026-11-17T18:30:00+00:00')`,
    sha,
  );
  await api.sql(`INSERT INTO lit_sources (day, n, data) VALUES ('2026-11-17', 0, ?1)`, packed);
}

describe('admin sources', () => {
  it('answers 401 with no sign-in and 403 to a signed-in user who is not the admin', async () => {
    await seed();
    const anonymous = await api.call('GET', '/v1/admin/sources');
    assert.equal(anonymous.status, 401);
    assert.doesNotMatch(JSON.stringify(anonymous.body), /synthetic|SYN/);
    const email = 'sam@example.test';
    const up = await api.call('POST', '/v1/signup', {
      body: {
        name: 'Sam Rivera',
        email,
        key: fakeKey(email),
        email_salt: createHash('sha256').update(`snowlight-v1|${email}`).digest('base64url'),
        name_key: fakeKey(`name|${email}`),
        name_salt: Buffer.alloc(16, 3).toString('base64url'),
        username: 'snowfan_sources',
        over13: true,
      },
      ip: '198.51.100.20',
    });
    assert.equal(up.status, 201);
    const user = await api.call('GET', '/v1/admin/sources', { token: up.body.token });
    assert.equal(user.status, 403);
    assert.doesNotMatch(JSON.stringify(user.body), /synthetic|SYN/);
    // the public routes carry no source either
    const overrides = await api.call('GET', '/v1/overrides');
    assert.doesNotMatch(JSON.stringify(overrides.body), /synthetic|source/);
  });

  it('gives the admin the stored parts, which decode to the summary', async () => {
    const login = await api.call('POST', '/v1/login', {
      body: { login: 'olivia', key: ADMIN_KEY },
      ip: '198.51.100.21',
    });
    assert.equal(login.status, 200);
    const r = await api.call('GET', '/v1/admin/sources', { token: login.body.token });
    assert.equal(r.status, 200);
    assert.equal(r.body.days.length, 1);
    const [day] = r.body.days;
    assert.equal(day.day, '2026-11-17');
    assert.equal(day.closings, 1);
    assert.equal(day.published_at, '2026-11-17T18:00:05+00:00');
    assert.equal(day.mode, 'shadow');
    assert.equal(day.latest_at, '2026-11-17T18:30:00+00:00');
    const raw = Buffer.concat(day.parts.map((p: string) => Buffer.from(p, 'base64')));
    const text = Buffer.from(gunzipSync(raw)).toString();
    assert.equal(text, SUMMARY);
    assert.equal(createHash('sha256').update(text).digest('hex'), day.sha256);
  });
});
