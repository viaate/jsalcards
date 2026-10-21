import assert from 'node:assert/strict';
import { createHash, generateKeyPairSync, randomBytes } from 'node:crypto';
import { after, before, describe, it } from 'node:test';
import { ADMIN_KEY, fakeKey, startApi, type Api } from './harness.ts';

let api: Api;
let ipCounter = 0;
const ip = () => `198.18.${++ipCounter % 250}.9`;

before(async () => {
  api = await startApi();
});
after(async () => {
  await api.close();
});

let userCounter = 0;
async function signup(): Promise<{ token: string; id: string; email: string }> {
  const n = ++userCounter;
  const email = `push${n}@example.com`;
  const r = await api.call('POST', '/v1/signup', {
    body: {
      name: 'Pat Lee',
      email,
      key: fakeKey(email),
      email_salt: createHash('sha256').update(`snowlight-v1|${email}`).digest('base64url'),
      name_key: fakeKey(`name|${email}`),
      name_salt: Buffer.alloc(16, n).toString('base64url'),
      username: `pusher_${n}`,
      over13: true,
    },
    ip: ip(),
  });
  assert.equal(r.status, 201, JSON.stringify(r.body));
  return { token: r.body.token, id: r.body.user.id, email };
}

/** A subscription as a browser makes one: a P-256 public key and 16 random auth bytes. */
function subscription(
  host = 'fcm.googleapis.com',
  path = `/fcm/send/${Buffer.from(randomBytes(8)).toString('hex')}`,
) {
  const { publicKey } = generateKeyPairSync('ec', { namedCurve: 'P-256' });
  const jwk = publicKey.export({ format: 'jwk' });
  const point = Buffer.concat([
    Buffer.from([4]),
    Buffer.from(jwk.x!, 'base64url'),
    Buffer.from(jwk.y!, 'base64url'),
  ]);
  return {
    endpoint: `https://${host}${path}`,
    keys: {
      p256dh: point.toString('base64url'),
      auth: Buffer.from(randomBytes(16)).toString('base64url'),
    },
  };
}

describe('the push key', () => {
  it('answers 404 until the deploy made one, then serves only the public key', async () => {
    const none = await api.call('GET', '/v1/push/key');
    assert.equal(none.status, 404);
    assert.equal(none.body.error, 'push_off');
    const pub = subscription().keys.p256dh;
    await api.sql(
      "INSERT INTO settings (name, value) VALUES ('vapid_public', ?1), ('vapid_private', 'secret-d')",
      pub,
    );
    const r = await api.call('GET', '/v1/push/key');
    assert.equal(r.status, 200);
    assert.deepEqual(r.body, { key: pub });
    assert.equal(r.headers.get('Access-Control-Allow-Origin'), 'https://snowlightmap.com');
    assert.ok(!JSON.stringify(r.body).includes('secret-d'));
  });
});

describe('push subscriptions', () => {
  it('needs a session', async () => {
    const r = await api.call('PUT', '/v1/me/push', { body: { subscription: subscription() } });
    assert.equal(r.status, 401);
  });

  it('keeps a subscription once, and moves a browser to the account that turned it on last', async () => {
    const a = await signup();
    const b = await signup();
    const sub = subscription();
    for (let i = 0; i < 2; i++) {
      const r = await api.call('PUT', '/v1/me/push', {
        token: a.token,
        body: { subscription: sub },
      });
      assert.equal(r.status, 200);
      assert.deepEqual(r.body, { devices: 1 });
    }
    const moved = await api.call('PUT', '/v1/me/push', {
      token: b.token,
      body: { subscription: sub },
    });
    assert.deepEqual(moved.body, { devices: 1 });
    const rows = await api.sql(
      'SELECT user_id FROM push_subscriptions WHERE endpoint = ?1',
      sub.endpoint,
    );
    assert.deepEqual(rows, [{ user_id: b.id }]);
    const left = await api.call('GET', '/v1/me/notify', { token: a.token });
    assert.equal(left.body.devices, 0);
  });

  it('keeps the newest 5 browsers of an account', async () => {
    const a = await signup();
    const subs = Array.from({ length: 7 }, () => subscription());
    for (const [i, sub] of subs.entries()) {
      const r = await api.call('PUT', '/v1/me/push', {
        token: a.token,
        body: { subscription: sub },
      });
      assert.equal(r.body.devices, Math.min(i + 1, 5));
      await api.sql(
        'UPDATE push_subscriptions SET created_at = ?2 WHERE endpoint = ?1',
        sub.endpoint,
        i,
      );
    }
    const rows = await api.sql(
      'SELECT endpoint FROM push_subscriptions WHERE user_id = ?1 ORDER BY created_at',
      a.id,
    );
    assert.deepEqual(
      rows.map((row) => row.endpoint),
      subs.slice(2).map((sub) => sub.endpoint),
    );
  });

  it('takes the push services of Chrome, Edge, Firefox and Safari, and nothing else', async () => {
    const a = await signup();
    for (const host of [
      'fcm.googleapis.com',
      'updates.push.services.mozilla.com',
      'web.push.apple.com',
      'wns2-by3p.notify.windows.com',
    ]) {
      const r = await api.call('PUT', '/v1/me/push', {
        token: a.token,
        body: { subscription: subscription(host) },
      });
      assert.equal(r.status, 200, host);
    }
    const bad = [
      subscription('example.com'),
      subscription('fcm.googleapis.com.evil.example'),
      { ...subscription(), endpoint: 'http://fcm.googleapis.com/fcm/send/x' },
      { ...subscription(), endpoint: 'https://fcm.googleapis.com:8443/fcm/send/x' },
      { ...subscription(), endpoint: 'https://user@fcm.googleapis.com/fcm/send/x' },
      { ...subscription(), endpoint: `https://fcm.googleapis.com/${'x'.repeat(1100)}` },
      { ...subscription(), keys: { p256dh: 'short', auth: subscription().keys.auth } },
      { ...subscription(), keys: { p256dh: subscription().keys.p256dh, auth: 'x' } },
      { endpoint: subscription().endpoint },
      'not an object',
    ];
    for (const sub of bad) {
      const r = await api.call('PUT', '/v1/me/push', {
        token: a.token,
        body: { subscription: sub },
      });
      assert.equal(r.status, 400, JSON.stringify(sub).slice(0, 80));
      assert.equal(r.body.error, 'bad_subscription');
    }
  });

  it('removes only this account’s subscription on DELETE', async () => {
    const a = await signup();
    const b = await signup();
    const sub = subscription();
    await api.call('PUT', '/v1/me/push', { token: a.token, body: { subscription: sub } });
    const other = await api.call('DELETE', '/v1/me/push', {
      token: b.token,
      body: { endpoint: sub.endpoint },
    });
    assert.equal(other.status, 200);
    assert.equal(
      (await api.sql('SELECT 1 FROM push_subscriptions WHERE endpoint = ?1', sub.endpoint)).length,
      1,
    );
    const mine = await api.call('DELETE', '/v1/me/push', {
      token: a.token,
      body: { endpoint: sub.endpoint },
    });
    assert.deepEqual(mine.body, { devices: 0 });
  });
});

describe('notifications end with the sign-in', () => {
  async function login(email: string): Promise<string> {
    const r = await api.call('POST', '/v1/login', {
      body: { login: email, key: fakeKey(email) },
      ip: ip(),
    });
    assert.equal(r.status, 200, JSON.stringify(r.body));
    return r.body.token;
  }
  async function admin(): Promise<string> {
    const r = await api.call('POST', '/v1/login', {
      body: { login: 'olivia', key: ADMIN_KEY },
      ip: ip(),
    });
    return r.body.token;
  }
  async function endpoints(id: string): Promise<string[]> {
    const rows = await api.sql(
      'SELECT endpoint FROM push_subscriptions WHERE user_id = ?1 ORDER BY endpoint',
      id,
    );
    return rows.map((row) => String(row.endpoint));
  }
  /** Two browsers of one account, each signed in on its own. */
  async function twoBrowsers() {
    const a = await signup();
    const other = await login(a.email);
    const here = subscription();
    const there = subscription();
    await api.call('PUT', '/v1/me/push', { token: a.token, body: { subscription: here } });
    await api.call('PUT', '/v1/me/push', { token: other, body: { subscription: there } });
    assert.equal((await endpoints(a.id)).length, 2);
    return { a, other, here, there };
  }

  it('keeps the sign-in each browser was turned on in', async () => {
    const { a, other, here, there } = await twoBrowsers();
    const rows = await api.sql(
      `SELECT p.endpoint AS endpoint, s.token_hash = p.session_hash AS same
         FROM push_subscriptions p JOIN sessions s ON s.token_hash = p.session_hash
        WHERE p.user_id = ?1 ORDER BY p.endpoint`,
      a.id,
    );
    assert.equal(rows.length, 2);
    assert.ok(rows.every((row) => row.same === 1));
    assert.ok([here.endpoint, there.endpoint].every((e) => rows.some((r) => r.endpoint === e)));
    assert.ok(other !== a.token);
  });

  it('stops every other browser on a password change and keeps this one', async () => {
    const { a, other, here } = await twoBrowsers();
    const changed = await api.call('PATCH', '/v1/me', {
      token: a.token,
      body: { current_key: fakeKey(a.email), new_key: fakeKey('push-new') },
    });
    assert.equal(changed.status, 200, JSON.stringify(changed.body));
    assert.deepEqual(await endpoints(a.id), [here.endpoint]);
    assert.equal((await api.call('GET', '/v1/me', { token: other })).status, 401);
    const read = await api.call('GET', '/v1/me/notify', { token: changed.body.token });
    assert.equal(read.body.devices, 1, 'this browser carries over to the new sign-in');
  });

  it('stops every browser on an admin password reset or disable', async () => {
    const token = await admin();
    const one = await twoBrowsers();
    const reset = await api.call('POST', `/v1/admin/users/${one.a.id}/reset-password`, {
      token,
      body: { key: fakeKey('temporary') },
    });
    assert.equal(reset.status, 200, JSON.stringify(reset.body));
    assert.deepEqual(await endpoints(one.a.id), []);
    const two = await twoBrowsers();
    const off = await api.call('POST', `/v1/admin/users/${two.a.id}/disable`, { token });
    assert.equal(off.status, 200);
    assert.deepEqual(await endpoints(two.a.id), []);
  });

  it('stops this browser on log out, and leaves the other', async () => {
    const { a, other, there } = await twoBrowsers();
    assert.equal((await api.call('POST', '/v1/logout', { token: a.token })).status, 200);
    assert.deepEqual(await endpoints(a.id), [there.endpoint]);
    const read = await api.call('GET', '/v1/me/notify', { token: other });
    assert.equal(read.body.devices, 1);
  });

  it('turns off every browser of the account at once', async () => {
    const { a, other } = await twoBrowsers();
    const b = await signup();
    await api.call('PUT', '/v1/me/push', {
      token: b.token,
      body: { subscription: subscription() },
    });
    const r = await api.call('DELETE', '/v1/me/push', { token: a.token, body: { all: true } });
    assert.equal(r.status, 200);
    assert.deepEqual(r.body, { devices: 0 });
    assert.deepEqual(await endpoints(a.id), []);
    assert.equal((await endpoints(b.id)).length, 1, 'another account keeps its own');
    assert.equal((await api.call('GET', '/v1/me', { token: other })).status, 200);
  });

  it('counts only browsers whose sign-in lasts, and an expired one ends its browser', async () => {
    const { a, other, here } = await twoBrowsers();
    const hash = createHash('sha256').update(other).digest('base64url');
    await api.sql('UPDATE sessions SET expires_at = 1 WHERE token_hash = ?1', hash);
    const read = await api.call('GET', '/v1/me/notify', { token: a.token });
    assert.equal(read.body.devices, 1);
    assert.equal((await api.call('GET', '/v1/me', { token: other })).status, 401);
    assert.deepEqual(await endpoints(a.id), [here.endpoint]);
  });
});

describe('notification settings', () => {
  it('starts at the defaults', async () => {
    const a = await signup();
    const r = await api.call('GET', '/v1/me/notify', { token: a.token });
    assert.equal(r.status, 200);
    assert.deepEqual(r.body, {
      settings: {
        status: true,
        chance: true,
        threshold: 50,
        night_before: false,
        night_time: '20:00',
        quiet_from: '22:00',
        quiet_to: '05:00',
      },
      devices: 0,
    });
  });

  it('changes what it is given and keeps the rest', async () => {
    const a = await signup();
    const r = await api.call('PATCH', '/v1/me/notify', {
      token: a.token,
      body: { threshold: 30, night_before: true, night_time: '19:30' },
    });
    assert.equal(r.status, 200);
    assert.equal(r.body.settings.threshold, 30);
    assert.equal(r.body.settings.night_before, true);
    assert.equal(r.body.settings.night_time, '19:30');
    assert.equal(r.body.settings.status, true);
    const again = await api.call('PATCH', '/v1/me/notify', {
      token: a.token,
      body: { chance: false },
    });
    assert.equal(again.body.settings.threshold, 30);
    assert.equal(again.body.settings.chance, false);
    const read = await api.call('GET', '/v1/me/notify', { token: a.token });
    assert.deepEqual(read.body.settings, again.body.settings);
  });

  it('refuses a value out of range and changes nothing', async () => {
    const a = await signup();
    for (const body of [
      { threshold: 40 },
      { threshold: '50' },
      { status: 1 },
      { night_time: '20:15' },
      { night_time: '24:00' },
      { quiet_from: '22:30' },
      { quiet_to: 5 },
      { volume: 11 },
      { chance: false, threshold: 99 },
    ]) {
      const r = await api.call('PATCH', '/v1/me/notify', { token: a.token, body });
      assert.equal(r.status, 400, JSON.stringify(body));
      assert.equal(r.body.error, 'bad_settings');
    }
    const read = await api.call('GET', '/v1/me/notify', { token: a.token });
    assert.equal(read.body.settings.chance, true);
  });
});

describe('deleting an account', () => {
  it('removes its subscriptions, settings and sent log', async () => {
    const a = await signup();
    await api.call('PUT', '/v1/me/push', {
      token: a.token,
      body: { subscription: subscription() },
    });
    await api.call('PATCH', '/v1/me/notify', { token: a.token, body: { threshold: 70 } });
    await api.sql(
      "INSERT INTO notify_sent (user_id, school_id, kind, day, value, sent_at) VALUES (?1, '390437801234', 'status', '2026-01-14', 'closed', 1)",
      a.id,
    );
    const r = await api.call('DELETE', '/v1/me', {
      token: a.token,
      body: { key: fakeKey(a.email) },
    });
    assert.equal(r.status, 200);
    for (const table of ['push_subscriptions', 'notify_settings', 'notify_sent'])
      assert.deepEqual(await api.sql(`SELECT * FROM ${table} WHERE user_id = ?1`, a.id), [], table);
  });

  it('removes them when the admin deletes it too', async () => {
    const a = await signup();
    await api.call('PUT', '/v1/me/push', {
      token: a.token,
      body: { subscription: subscription() },
    });
    const login = await api.call('POST', '/v1/login', {
      body: { login: 'olivia', key: ADMIN_KEY },
      ip: ip(),
    });
    const r = await api.call('DELETE', `/v1/admin/users/${a.id}`, { token: login.body.token });
    assert.equal(r.status, 200);
    assert.deepEqual(
      await api.sql('SELECT * FROM push_subscriptions WHERE user_id = ?1', a.id),
      [],
    );
  });
});

describe('the migration', () => {
  it('only adds: accounts and statuses made before it stay as they were', async () => {
    const old = await startApi({}, { skipMigrations: (file) => file.startsWith('0004') });
    try {
      const email = 'before@example.com';
      const r = await old.call('POST', '/v1/signup', {
        body: {
          name: 'Early Bird',
          email,
          key: fakeKey(email),
          email_salt: createHash('sha256').update(`snowlight-v1|${email}`).digest('base64url'),
          name_key: fakeKey(`name|${email}`),
          name_salt: Buffer.alloc(16, 3).toString('base64url'),
          username: 'early_bird',
          over13: true,
        },
      });
      assert.equal(r.status, 201);
      const before = await old.sql('SELECT * FROM users ORDER BY id');
      const settings = await old.sql('SELECT * FROM settings ORDER BY name');
      await old.migrate('0004_notify.sql');
      assert.deepEqual(await old.sql('SELECT * FROM users ORDER BY id'), before);
      assert.deepEqual(await old.sql('SELECT * FROM settings ORDER BY name'), settings);
      const me = await old.call('GET', '/v1/me/notify', { token: r.body.token });
      assert.equal(me.status, 200);
      assert.equal(me.body.settings.threshold, 50);
    } finally {
      await old.close();
    }
  });
});

describe('the VAPID key pair (scripts/vapid.mjs)', () => {
  it('makes a P-256 pair whose private key signs for its public key', async () => {
    const { makeKeys } = await import('../scripts/vapid.mjs' as string);
    const keys = makeKeys() as { publicKey: string; privateKey: string };
    const point = Buffer.from(keys.publicKey, 'base64url');
    assert.equal(point.length, 65);
    assert.equal(point[0], 4);
    assert.equal(Buffer.from(keys.privateKey, 'base64url').length, 32);
    const jwk = {
      kty: 'EC',
      crv: 'P-256',
      x: point.subarray(1, 33).toString('base64url'),
      y: point.subarray(33).toString('base64url'),
    };
    const { createPrivateKey, createPublicKey, sign, verify } = await import('node:crypto');
    const signer = createPrivateKey({ key: { ...jwk, d: keys.privateKey }, format: 'jwk' });
    const signature = sign('sha256', Buffer.from('push'), signer);
    assert.ok(
      verify(
        'sha256',
        Buffer.from('push'),
        createPublicKey({ key: jwk, format: 'jwk' }),
        signature,
      ),
    );
  });

  it('stores a pair once, with the keys as bound parameters, and keeps it after', async () => {
    const { ensureKeys } = await import('../scripts/vapid.mjs' as string);
    const sent: string[] = [];
    // A stand-in for the Cloudflare D1 query endpoint, over this test's database.
    const fakeFetch = async (
      url: string,
      init: { body: string; headers: Record<string, string> },
    ) => {
      sent.push(init.body);
      assert.match(url, /\/accounts\/acct\/d1\/database\/0{8}-0{4}-0{4}-0{4}-0{12}\/query$/);
      assert.equal(init.headers.Authorization, 'Bearer tok');
      const { sql, params } = JSON.parse(init.body) as { sql: string; params: string[] };
      assert.ok(!sql.includes(params[1]!), 'the private key is never in the SQL text');
      const before = await api.sql("SELECT COUNT(*) AS n FROM settings WHERE name LIKE 'vapid_%'");
      await api.sql(sql, ...params);
      const after = await api.sql("SELECT COUNT(*) AS n FROM settings WHERE name LIKE 'vapid_%'");
      return new Response(
        JSON.stringify({
          success: true,
          result: [{ meta: { changes: after[0].n - before[0].n } }],
        }),
      );
    };
    const fresh = await startApi();
    const was = api;
    api = fresh;
    try {
      const options = {
        token: 'tok',
        account: 'acct',
        database: '00000000-0000-0000-0000-000000000000',
        base: 'https://cf.test',
        fetch: fakeFetch,
      };
      assert.equal(await ensureKeys(options), 'made');
      const first = await api.sql(
        "SELECT name, value FROM settings WHERE name LIKE 'vapid_%' ORDER BY name",
      );
      assert.deepEqual(
        first.map((row) => row.name),
        ['vapid_private', 'vapid_public'],
      );
      assert.equal(await ensureKeys(options), 'kept');
      assert.deepEqual(
        await api.sql("SELECT name, value FROM settings WHERE name LIKE 'vapid_%' ORDER BY name"),
        first,
      );
      const served = await api.call('GET', '/v1/push/key');
      assert.equal(served.body.key, first[1].value);
      assert.equal(sent.length, 2);
      await assert.rejects(
        ensureKeys({ ...options, fetch: async () => new Response('{}', { status: 403 }) }),
        /HTTP 403$/,
      );
    } finally {
      api = was;
      await fresh.close();
    }
  });
});
