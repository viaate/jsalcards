import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { after, before, describe, it } from 'node:test';
import { addDays, endOfDay, localDate } from '../src/days.ts';
import { ADMIN_KEY, ORIGIN, fakeKey, startApi, type Api } from './harness.ts';

let api: Api;
let ipCounter = 0;
/** A fresh client address, so one test's rate limit never touches another's. */
const ip = () => `198.51.100.${++ipCounter}`;

before(async () => {
  api = await startApi();
});
after(async () => {
  await api.close();
});

async function signup(email: string, name = 'Sam Rivera', key = fakeKey(email)) {
  return api.call('POST', '/v1/signup', { body: { name, email, key, over13: true }, ip: ip() });
}

async function adminToken(): Promise<string> {
  const r = await api.call('POST', '/v1/login', {
    body: { login: 'olivia', key: ADMIN_KEY },
    ip: ip(),
  });
  assert.equal(r.status, 200);
  return r.body.token;
}

const ZONE = 'America/New_York';
/** The zone's today and tomorrow, by the test machine's clock. */
const today = () => localDate(Date.now(), ZONE);
const tomorrow = () => addDays(today(), 1);

describe('health and CORS', () => {
  it('answers health with the allowed origin echoed', async () => {
    const r = await api.call('GET', '/v1/health');
    assert.equal(r.status, 200);
    assert.deepEqual(r.body, { ok: true, api: 1 });
    assert.equal(r.headers.get('Access-Control-Allow-Origin'), 'https://snowlightmap.com');
  });

  it('grants no CORS to another site and refuses its writes', async () => {
    const read = await api.call('GET', '/v1/health', { origin: 'https://evil.example' });
    assert.equal(read.headers.get('Access-Control-Allow-Origin'), null);
    const write = await api.call('POST', '/v1/signup', {
      origin: 'https://evil.example',
      body: { name: 'A', email: 'a@b.co', key: fakeKey('x'), over13: true },
    });
    assert.equal(write.status, 403);
  });

  it('does not allow localhost outside local dev', async () => {
    const r = await api.call('OPTIONS', '/v1/login', { origin: 'http://localhost:5173' });
    assert.equal(r.headers.get('Access-Control-Allow-Origin'), null);
  });

  it('answers a preflight from the site', async () => {
    const r = await api.call('OPTIONS', '/v1/login');
    assert.equal(r.status, 204);
    assert.match(r.headers.get('Access-Control-Allow-Headers') ?? '', /Authorization/);
  });

  it('takes JSON bodies only, and small ones', async () => {
    const form = await api.call('POST', '/v1/login', {
      body: { login: 'a@b.co', key: fakeKey('a') },
      headers: { 'Content-Type': 'text/plain' },
      ip: ip(),
    });
    assert.equal(form.status, 415);
    const big = await api.call('POST', '/v1/login', {
      body: { login: 'a@b.co', pad: 'x'.repeat(5000) },
      ip: ip(),
    });
    assert.equal(big.status, 413);
  });
});

describe('sign up and log in', () => {
  it('signs up, then logs in with the same key', async () => {
    const r = await signup('Sam@Example.com');
    assert.equal(r.status, 201);
    assert.match(r.body.token, /^[A-Za-z0-9_-]{43}$/);
    assert.equal(r.body.user.email, 'sam@example.com');
    assert.equal(r.body.user.role, 'user');
    assert.equal(r.body.user.name, 'Sam Rivera');
    const login = await api.call('POST', '/v1/login', {
      body: { login: ' SAM@example.com ', key: fakeKey('Sam@Example.com') },
      ip: ip(),
    });
    assert.equal(login.status, 200);
    const me = await api.call('GET', '/v1/me', { token: login.body.token });
    assert.equal(me.status, 200);
    assert.equal(me.body.user.email, 'sam@example.com');
  });

  it('stores only a salted hash of the key, never the key', async () => {
    const key = fakeKey('stored');
    await signup('stored@example.com', 'Stored', key);
    const [row] = await api.sql('SELECT * FROM users WHERE login = ?1', 'stored@example.com');
    assert.ok(row.salt && row.key_hash);
    assert.ok(!JSON.stringify(row).includes(key));
    const sessions = await api.sql('SELECT token_hash FROM sessions WHERE user_id = ?1', row.id);
    assert.equal(sessions.length, 1);
  });

  it('refuses a second account on the same email', async () => {
    await signup('twice@example.com');
    const again = await signup('TWICE@example.com');
    assert.equal(again.status, 409);
  });

  it('requires confirming 13 or older', async () => {
    const r = await api.call('POST', '/v1/signup', {
      body: { name: 'Kid', email: 'kid@example.com', key: fakeKey('k'), over13: false },
      ip: ip(),
    });
    assert.equal(r.status, 400);
    assert.equal(r.body.error, 'over13_required');
  });

  it('checks name, email and key formats', async () => {
    const base = { name: 'Ok', email: 'ok@example.com', key: fakeKey('ok'), over13: true };
    for (const [field, value] of [
      ['name', ''],
      ['name', 'x'.repeat(41)],
      ['name', '<b>bold</b>'],
      ['name', 'tab\there'],
      ['email', 'not-an-email'],
      ['key', 'short'],
      ['key', 'a password in the clear!'],
    ] as const) {
      const r = await api.call('POST', '/v1/signup', {
        body: { ...base, [field]: value },
        ip: ip(),
      });
      assert.equal(r.status, 400, `${field}=${value}`);
    }
  });

  it('gives one answer for a wrong password and an unknown account', async () => {
    await signup('wrong@example.com');
    const wrong = await api.call('POST', '/v1/login', {
      body: { login: 'wrong@example.com', key: fakeKey('nope') },
      ip: ip(),
    });
    const unknown = await api.call('POST', '/v1/login', {
      body: { login: 'nobody@example.com', key: fakeKey('nope') },
      ip: ip(),
    });
    assert.equal(wrong.status, 401);
    assert.deepEqual(wrong.body, unknown.body);
    assert.equal(unknown.status, 401);
  });
});

describe('rate limits', () => {
  it('stops logins after 10 failures per address in 15 minutes', async () => {
    const address = ip();
    for (let i = 0; i < 10; i++) {
      const r = await api.call('POST', '/v1/login', {
        body: { login: `x${i}@example.com`, key: fakeKey('bad') },
        ip: address,
      });
      assert.equal(r.status, 401);
    }
    const blocked = await api.call('POST', '/v1/login', {
      body: { login: 'y@example.com', key: fakeKey('bad') },
      ip: address,
    });
    assert.equal(blocked.status, 429);
  });

  it('stops logins after 10 failures per account from any address', async () => {
    const key = fakeKey('target@example.com');
    await signup('target@example.com', 'Target', key);
    for (let i = 0; i < 10; i++) {
      await api.call('POST', '/v1/login', {
        body: { login: 'target@example.com', key: fakeKey(`g${i}`) },
        ip: ip(),
      });
    }
    const right = await api.call('POST', '/v1/login', {
      body: { login: 'target@example.com', key },
      ip: ip(),
    });
    assert.equal(right.status, 429);
    // The window passes: the account can log in again.
    await api.sql('UPDATE rate_limits SET window_start = window_start - 16 * 60 * 1000');
    const later = await api.call('POST', '/v1/login', {
      body: { login: 'target@example.com', key },
      ip: ip(),
    });
    assert.equal(later.status, 200);
  });

  it('allows 5 signups per address per hour', async () => {
    const address = ip();
    for (let i = 0; i < 5; i++) {
      const r = await api.call('POST', '/v1/signup', {
        body: { name: 'N', email: `many${i}@example.com`, key: fakeKey(`m${i}`), over13: true },
        ip: address,
      });
      assert.equal(r.status, 201);
    }
    const sixth = await api.call('POST', '/v1/signup', {
      body: { name: 'N', email: 'many5@example.com', key: fakeKey('m5'), over13: true },
      ip: address,
    });
    assert.equal(sixth.status, 429);
  });

  it('checks at most 10 of 60 wrong logins sent at once from one address', async () => {
    await signup('burst@example.com', 'Burst');
    const address = ip();
    const results = await Promise.all(
      Array.from({ length: 60 }, (_, i) =>
        api.call('POST', '/v1/login', {
          body: { login: 'burst@example.com', key: fakeKey(`burst${i}`) },
          ip: address,
        }),
      ),
    );
    const checked = results.filter((r) => r.status === 401).length;
    assert.equal(checked, 10);
    assert.equal(results.filter((r) => r.status === 429).length, 50);
  });

  it('checks at most 10 of 60 wrong logins sent at once for one account from many addresses', async () => {
    await signup('spread@example.com', 'Spread');
    const results = await Promise.all(
      Array.from({ length: 60 }, (_, i) =>
        api.call('POST', '/v1/login', {
          body: { login: 'spread@example.com', key: fakeKey(`spread${i}`) },
          ip: `192.0.2.${i + 1}`,
        }),
      ),
    );
    assert.equal(results.filter((r) => r.status === 401).length, 10);
    await api.sql("DELETE FROM rate_limits WHERE bucket LIKE 'login-ip:%'");
  });

  it('lets at most 5 of 20 signups sent at once from one address through', async () => {
    const address = ip();
    const results = await Promise.all(
      Array.from({ length: 20 }, (_, i) =>
        api.call('POST', '/v1/signup', {
          body: { name: 'N', email: `rush${i}@example.com`, key: fakeKey(`r${i}`), over13: true },
          ip: address,
        }),
      ),
    );
    assert.equal(results.filter((r) => r.status === 201).length, 5);
    assert.equal(results.filter((r) => r.status === 429).length, 15);
  });

  it('does not count right logins against the limit', async () => {
    const key = fakeKey('often@example.com');
    await signup('often@example.com', 'Often', key);
    const address = ip();
    for (let i = 0; i < 15; i++) {
      const r = await api.call('POST', '/v1/login', {
        body: { login: 'often@example.com', key },
        ip: address,
      });
      assert.equal(r.status, 200);
    }
  });

  it('keeps the admin login open from a network the admin used when others fill its account limit', async () => {
    const home = (n: number) => `100.64.5.${n}`;
    const first = await api.call('POST', '/v1/login', {
      body: { login: 'olivia', key: ADMIN_KEY },
      ip: home(1),
    });
    assert.equal(first.status, 200);
    const phone = await api.call('POST', '/v1/login', {
      body: { login: 'olivia', key: ADMIN_KEY },
      ip: '2001:db8:5:7:a::1',
    });
    assert.equal(phone.status, 200);
    for (let i = 0; i < 12; i++) {
      await api.call('POST', '/v1/login', {
        body: { login: 'olivia', key: fakeKey(`guess${i}`) },
        ip: `192.0.2.${100 + i}`,
      });
    }
    // A new network waits out the window.
    const stranger = await api.call('POST', '/v1/login', {
      body: { login: 'Olivia', key: ADMIN_KEY },
      ip: '203.0.113.200',
    });
    assert.equal(stranger.status, 429);
    // Another address on the admin's networks still gets in.
    const again = await api.call('POST', '/v1/login', {
      body: { login: 'Olivia', key: ADMIN_KEY },
      ip: home(77),
    });
    assert.equal(again.status, 200);
    const again6 = await api.call('POST', '/v1/login', {
      body: { login: 'olivia', key: ADMIN_KEY },
      ip: '2001:db8:5:7:ffff:1:2:3',
    });
    assert.equal(again6.status, 200);
    // Wrong keys from there are still held to the per-address limit.
    const guesser = home(78);
    const tries = [];
    for (let i = 0; i < 12; i++) {
      tries.push(
        (
          await api.call('POST', '/v1/login', {
            body: { login: 'olivia', key: fakeKey(`near${i}`) },
            ip: guesser,
          })
        ).status,
      );
    }
    assert.deepEqual(tries, [...Array<number>(10).fill(401), 429, 429]);
    // A network known only for another account gets nothing.
    await signup('known@example.com', 'Known', fakeKey('known@example.com'));
    await api.call('POST', '/v1/login', {
      body: { login: 'known@example.com', key: fakeKey('known@example.com') },
      ip: '100.64.9.1',
    });
    const other = await api.call('POST', '/v1/login', {
      body: { login: 'olivia', key: ADMIN_KEY },
      ip: '100.64.9.2',
    });
    assert.equal(other.status, 429);
    await api.sql("DELETE FROM rate_limits WHERE bucket LIKE 'login-account:%'");
  });

  it('holds many addresses in a known admin network to one budget', async () => {
    const net = (n: number) => `100.64.6.${n}`;
    const first = await api.call('POST', '/v1/login', {
      body: { login: 'olivia', key: ADMIN_KEY },
      ip: net(1),
    });
    assert.equal(first.status, 200);
    for (let i = 0; i < 12; i++) {
      await api.call('POST', '/v1/login', {
        body: { login: 'olivia', key: fakeKey(`fill${i}`) },
        ip: `192.0.2.${150 + i}`,
      });
    }
    const tries = [];
    for (let i = 0; i < 50; i++) {
      tries.push(
        (
          await api.call('POST', '/v1/login', {
            body: { login: 'olivia', key: fakeKey(`spread${i}`) },
            ip: net(100 + i),
          })
        ).status,
      );
    }
    assert.deepEqual(tries, [...Array<number>(10).fill(401), ...Array<number>(40).fill(429)]);
    await api.sql(
      "DELETE FROM rate_limits WHERE bucket LIKE 'login-account:%' OR bucket LIKE 'login-net:%'",
    );
  });

  it('keeps no address in the clear', async () => {
    const rows = await api.sql('SELECT bucket FROM rate_limits');
    assert.ok(rows.length > 0);
    for (const row of rows) {
      assert.ok(!/198\.51\.100|100\.64|192\.0\.2|2001:db8/.test(String(row.bucket)));
    }
  });
});

describe('sessions', () => {
  it('ends on logout', async () => {
    const { body } = await signup('logout@example.com');
    assert.equal((await api.call('POST', '/v1/logout', { token: body.token })).status, 200);
    assert.equal((await api.call('GET', '/v1/me', { token: body.token })).status, 401);
  });

  it('ends when it expires, and slides forward when used', async () => {
    const { body } = await signup('expiry@example.com');
    await api.sql(
      'UPDATE sessions SET refreshed_at = refreshed_at - 2 * 3600 * 1000 WHERE user_id = ?1',
      body.user.id,
    );
    const [before] = await api.sql(
      'SELECT expires_at FROM sessions WHERE user_id = ?1',
      body.user.id,
    );
    await api.call('GET', '/v1/me', { token: body.token });
    const [slid] = await api.sql(
      'SELECT expires_at FROM sessions WHERE user_id = ?1',
      body.user.id,
    );
    assert.ok(slid.expires_at >= before.expires_at);
    await api.sql(
      'UPDATE sessions SET expires_at = ?2 WHERE user_id = ?1',
      body.user.id,
      Date.now() - 1000,
    );
    assert.equal((await api.call('GET', '/v1/me', { token: body.token })).status, 401);
    assert.equal(
      (await api.sql('SELECT * FROM sessions WHERE user_id = ?1', body.user.id)).length,
      0,
    );
  });

  it('ends everywhere on a password change, and the new key works', async () => {
    const oldKey = fakeKey('pw-old');
    const { body } = await signup('pw@example.com', 'Pw', oldKey);
    const second = await api.call('POST', '/v1/login', {
      body: { login: 'pw@example.com', key: oldKey },
      ip: ip(),
    });
    const wrong = await api.call('PATCH', '/v1/me', {
      token: body.token,
      body: { current_key: fakeKey('not-it'), new_key: fakeKey('pw-new') },
    });
    assert.equal(wrong.status, 403);
    const changed = await api.call('PATCH', '/v1/me', {
      token: body.token,
      body: { current_key: oldKey, new_key: fakeKey('pw-new') },
    });
    assert.equal(changed.status, 200);
    assert.ok(changed.body.token);
    assert.equal((await api.call('GET', '/v1/me', { token: body.token })).status, 401);
    assert.equal((await api.call('GET', '/v1/me', { token: second.body.token })).status, 401);
    assert.equal((await api.call('GET', '/v1/me', { token: changed.body.token })).status, 200);
    const relog = await api.call('POST', '/v1/login', {
      body: { login: 'pw@example.com', key: fakeKey('pw-new') },
      ip: ip(),
    });
    assert.equal(relog.status, 200);
  });

  it('changes email only with the password, and moves the login', async () => {
    const key = fakeKey('mail-old');
    const { body } = await signup('mail@example.com', 'Mail', key);
    const noKey = await api.call('PATCH', '/v1/me', {
      token: body.token,
      body: { email: 'mail2@example.com' },
    });
    assert.equal(noKey.status, 403);
    const moved = await api.call('PATCH', '/v1/me', {
      token: body.token,
      body: { email: 'Mail2@example.com', current_key: key, new_key: fakeKey('mail-new') },
    });
    assert.equal(moved.status, 200);
    assert.equal(moved.body.user.email, 'mail2@example.com');
    const login = await api.call('POST', '/v1/login', {
      body: { login: 'mail2@example.com', key: fakeKey('mail-new') },
      ip: ip(),
    });
    assert.equal(login.status, 200);
  });

  it('renames without a password', async () => {
    const { body } = await signup('rename@example.com');
    const r = await api.call('PATCH', '/v1/me', {
      token: body.token,
      body: { name: '  Jo   Ann ' },
    });
    assert.equal(r.status, 200);
    assert.equal(r.body.user.name, 'Jo Ann');
  });

  it('deletes the account with the password', async () => {
    const key = fakeKey('del');
    const { body } = await signup('del@example.com', 'Del', key);
    assert.equal(
      (await api.call('DELETE', '/v1/me', { token: body.token, body: { key: fakeKey('x') } }))
        .status,
      403,
    );
    assert.equal(
      (await api.call('DELETE', '/v1/me', { token: body.token, body: { key } })).status,
      200,
    );
    assert.equal((await api.call('GET', '/v1/me', { token: body.token })).status, 401);
    assert.equal(
      (await api.sql('SELECT * FROM users WHERE login = ?1', 'del@example.com')).length,
      0,
    );
  });

  it('answers a malformed path with not found', async () => {
    const r = await api.call('DELETE', '/v1/admin/overrides/%E0%A4%A');
    assert.equal(r.status, 404);
  });

  it('refuses a malformed token', async () => {
    const r = await api.call('GET', '/v1/me', { headers: { Authorization: 'Bearer abc' } });
    assert.equal(r.status, 401);
  });
});

describe('saved schools', () => {
  it('keeps up to five, deduplicated', async () => {
    const { body } = await signup('schools@example.com');
    const schools = [
      { id: '390437801234', name: 'Lincoln Elementary' },
      { id: '390437801234', name: 'Lincoln Elementary' },
      { id: 'A1234567', name: 'St. Mary School' },
    ];
    const r = await api.call('PUT', '/v1/me/schools', { token: body.token, body: { schools } });
    assert.equal(r.status, 200);
    assert.equal(r.body.user.schools.length, 2);
    const six = Array.from({ length: 6 }, (_, i) => ({ id: `39043780123${i}`, name: `S${i}` }));
    assert.equal(
      (await api.call('PUT', '/v1/me/schools', { token: body.token, body: { schools: six } }))
        .status,
      400,
    );
    const bad = [{ id: '../etc', name: 'x' }];
    assert.equal(
      (await api.call('PUT', '/v1/me/schools', { token: body.token, body: { schools: bad } }))
        .status,
      400,
    );
    const me = await api.call('GET', '/v1/me', { token: body.token });
    assert.deepEqual(
      me.body.user.schools.map((s: { id: string }) => s.id),
      ['390437801234', 'A1234567'],
    );
  });
});

describe('the admin', () => {
  it('reserves the admin name: no account can sign up as it', async () => {
    const r = await api.call('POST', '/v1/signup', {
      body: { name: 'Olivia', email: 'Olivia', key: fakeKey('x'), over13: true },
      ip: ip(),
    });
    assert.equal(r.status, 400);
  });

  it('logs in case-insensitively with the derived key only', async () => {
    const wrong = await api.call('POST', '/v1/login', {
      body: { login: 'OLIVIA', key: fakeKey('guess') },
      ip: ip(),
    });
    assert.equal(wrong.status, 401);
    const r = await api.call('POST', '/v1/login', {
      body: { login: 'OLIVIA', key: ADMIN_KEY },
      ip: ip(),
    });
    assert.equal(r.status, 200);
    assert.equal(r.body.user.role, 'admin');
    assert.equal(r.body.user.name, 'Olivia');
    const rows = await api.sql("SELECT * FROM users WHERE role = 'admin'");
    assert.equal(rows.length, 1);
    // A stamp of the key its sessions are bound to, never the key.
    assert.match(rows[0].key_hash, /^[A-Za-z0-9_-]{43}$/);
    assert.notEqual(rows[0].key_hash, ADMIN_KEY);
  });

  it('ends admin sessions when the admin password changes', async () => {
    const first = await startApi();
    try {
      const login = await first.call('POST', '/v1/login', {
        body: { login: 'olivia', key: ADMIN_KEY },
        ip: ip(),
      });
      assert.equal(login.status, 200);
      const [row] = await first.sql("SELECT key_hash FROM users WHERE role = 'admin'");
      assert.ok(!String(row.key_hash).includes(ADMIN_KEY));
      assert.equal(
        (await first.call('GET', '/v1/admin/summary', { token: login.body.token })).status,
        200,
      );
      // The same database under a new ADMIN_KEY: the old session no longer counts.
      await first.mf.setOptions(
        (await import('miniflare')).convertV4MiniflareOptions({
          modules: true,
          script: first.script,
          compatibilityDate: '2026-08-01',
          d1Databases: ['DB'],
          bindings: {
            ADMIN_USERNAME: 'Olivia',
            ADMIN_KEY: fakeKey('new-secret'),
            ALLOWED_ORIGINS: ORIGIN,
          },
        }),
      );
      const after = await first.call('GET', '/v1/admin/summary', { token: login.body.token });
      assert.equal(after.status, 401);
      const old = await first.call('POST', '/v1/login', {
        body: { login: 'olivia', key: ADMIN_KEY },
        ip: ip(),
      });
      assert.equal(old.status, 401);
      const fresh = await first.call('POST', '/v1/login', {
        body: { login: 'olivia', key: fakeKey('new-secret') },
        ip: ip(),
      });
      assert.equal(fresh.status, 200);
      assert.equal(
        (await first.call('GET', '/v1/admin/summary', { token: fresh.body.token })).status,
        200,
      );
    } finally {
      await first.close();
    }
  });

  it('cannot log in at all when ADMIN_KEY is unset', async () => {
    const bare = await startApi({ ADMIN_KEY: '' });
    try {
      for (const key of [ADMIN_KEY, fakeKey('')]) {
        const r = await bare.call('POST', '/v1/login', {
          body: { login: 'olivia', key },
          ip: ip(),
        });
        assert.equal(r.status, 401);
      }
    } finally {
      await bare.close();
    }
  });

  it('is the only one who reaches admin routes', async () => {
    const { body } = await signup('plain@example.com');
    const routes: [string, string, unknown?][] = [
      ['GET', '/v1/admin/summary'],
      ['GET', '/v1/admin/users'],
      ['GET', '/v1/admin/overrides'],
      [
        'PUT',
        '/v1/admin/overrides',
        { scope: 'district', id: '3904378', status: 'closed', days: [today()], time_zone: ZONE },
      ],
      ['DELETE', '/v1/admin/overrides/district:3904378'],
      ['GET', '/v1/admin/audit'],
      ['POST', `/v1/admin/users/${body.user.id}/disable`],
      ['POST', `/v1/admin/users/${body.user.id}/reset-password`, { key: fakeKey('t') }],
      ['DELETE', `/v1/admin/users/${body.user.id}`],
    ];
    for (const [method, path, payload] of routes) {
      const signedOut = await api.call(method, path, {
        body: payload ?? (method === 'GET' ? undefined : {}),
      });
      assert.equal(signedOut.status, 401, `${method} ${path} signed out`);
      const user = await api.call(method, path, {
        token: body.token,
        body: payload ?? (method === 'GET' ? undefined : {}),
      });
      assert.equal(user.status, 403, `${method} ${path} as a user`);
    }
  });

  it('loses admin rights at once when the role changes in the database', async () => {
    const token = await adminToken();
    await api.sql("UPDATE users SET role = 'user' WHERE login = 'olivia'");
    assert.equal((await api.call('GET', '/v1/admin/summary', { token })).status, 403);
    await api.sql("UPDATE users SET role = 'admin' WHERE login = 'olivia'");
    assert.equal((await api.call('GET', '/v1/admin/summary', { token })).status, 200);
  });

  it('sees the summary and the user list, and finds by name or email', async () => {
    const token = await adminToken();
    await signup('findme@example.com', 'Findable Person');
    const summary = await api.call('GET', '/v1/admin/summary', { token });
    assert.equal(summary.status, 200);
    assert.ok(summary.body.accounts.total >= 1);
    assert.ok(summary.body.accounts.new_day >= 1);
    const list = await api.call('GET', '/v1/admin/users?q=findable', { token });
    assert.equal(list.body.users.length, 1);
    assert.equal(list.body.users[0].email, 'findme@example.com');
    assert.equal(list.body.users[0].schools, 0);
    const wild = await api.call('GET', '/v1/admin/users?q=%25', { token });
    assert.equal(wild.body.users.length, 0);
  });

  it('disables, enables, resets and deletes a user, with an audit trail', async () => {
    const token = await adminToken();
    const { body } = await signup('managed@example.com', 'Managed', fakeKey('managed'));
    const id = body.user.id;
    assert.equal((await api.call('POST', `/v1/admin/users/${id}/disable`, { token })).status, 200);
    assert.equal((await api.call('GET', '/v1/me', { token: body.token })).status, 401);
    const blocked = await api.call('POST', '/v1/login', {
      body: { login: 'managed@example.com', key: fakeKey('managed') },
      ip: ip(),
    });
    assert.equal(blocked.status, 401);
    assert.equal((await api.call('POST', `/v1/admin/users/${id}/enable`, { token })).status, 200);
    const reset = await api.call('POST', `/v1/admin/users/${id}/reset-password`, {
      token,
      body: { key: fakeKey('temp') },
    });
    assert.equal(reset.status, 200);
    const old = await api.call('POST', '/v1/login', {
      body: { login: 'managed@example.com', key: fakeKey('managed') },
      ip: ip(),
    });
    assert.equal(old.status, 401);
    const temp = await api.call('POST', '/v1/login', {
      body: { login: 'managed@example.com', key: fakeKey('temp') },
      ip: ip(),
    });
    assert.equal(temp.status, 200);
    assert.equal((await api.call('DELETE', `/v1/admin/users/${id}`, { token })).status, 200);
    assert.equal((await api.call('GET', '/v1/me', { token: temp.body.token })).status, 401);
    const log = await api.call('GET', '/v1/admin/audit', { token });
    const actions = log.body.entries.map((e: { action: string }) => e.action);
    for (const a of ['disable_user', 'enable_user', 'reset_password', 'delete_user'])
      assert.ok(actions.includes(a), a);
    assert.ok(!JSON.stringify(log.body).includes(fakeKey('temp')));
  });

  it('cannot be disabled or deleted through the user routes', async () => {
    const token = await adminToken();
    const [adminRow] = await api.sql("SELECT id FROM users WHERE role = 'admin'");
    assert.equal(
      (await api.call('POST', `/v1/admin/users/${adminRow.id}/disable`, { token })).status,
      400,
    );
    assert.equal(
      (await api.call('DELETE', `/v1/admin/users/${adminRow.id}`, { token })).status,
      400,
    );
    assert.equal(
      (
        await api.call('PATCH', '/v1/me', {
          token,
          body: { current_key: ADMIN_KEY, new_key: fakeKey('n') },
        })
      ).status,
      400,
    );
  });
});

describe('manual statuses', () => {
  it('validates every field', async () => {
    const token = await adminToken();
    const good = {
      scope: 'district',
      id: '3904378',
      status: 'closed',
      days: [today()],
      time_zone: ZONE,
    };
    const bad: Record<string, unknown>[] = [
      { ...good, scope: 'state' },
      { ...good, id: '390437' },
      { ...good, scope: 'school', id: '3904378' },
      { ...good, status: 'remote' },
      { ...good, status: 'delayed' },
      { ...good, status: 'delayed', minutes: 0 },
      { ...good, status: 'delayed', minutes: 241 },
      { ...good, status: 'delayed', minutes: 1.5 },
      { ...good, minutes: 60 },
      { ...good, status: 'early_dismissal' },
      { ...good, status: 'early_dismissal', at_local_time: '25:00' },
      { ...good, status: 'early_dismissal', at_local_time: '1:30 PM' },
      { ...good, note: '<script>' },
      { ...good, note: 'x'.repeat(201) },
      // Days: one or two, the zone's today and tomorrow, in order.
      { ...good, days: undefined },
      { ...good, days: [] },
      { ...good, days: today() },
      { ...good, days: [today(), tomorrow(), addDays(today(), 2)] },
      { ...good, days: [tomorrow(), today()] },
      { ...good, days: [today(), today()] },
      { ...good, days: [addDays(today(), -1)] },
      { ...good, days: [addDays(today(), -1), today()] },
      { ...good, days: [addDays(today(), 2)] },
      { ...good, days: ['2026-02-30'] },
      { ...good, days: ['tomorrow'] },
      { ...good, days: [`${today()}T00:00:00Z`] },
      { ...good, time_zone: undefined },
      { ...good, time_zone: 'Mars/Olympus_Mons' },
      { ...good, time_zone: 'UTC' },
      { ...good, time_zone: '../etc/passwd' },
      // A bare expiry, as the first admin form sent, is not enough.
      { scope: 'district', id: '3904378', status: 'closed', expires_at: '2030-01-01T00:00:00Z' },
    ];
    for (const body of bad) {
      const r = await api.call('PUT', '/v1/admin/overrides', { token, body });
      assert.equal(r.status, 400, JSON.stringify(body));
    }
    const ok = [
      good,
      { ...good, days: [tomorrow()] },
      { ...good, days: [today(), tomorrow()] },
      { ...good, time_zone: 'America/Indiana/Indianapolis' },
      { ...good, scope: 'school', id: '390437801234', status: 'delayed', minutes: 120 },
      {
        ...good,
        scope: 'school',
        id: 'A1234567',
        status: 'early_dismissal',
        at_local_time: '13:30',
      },
      { ...good, id: '3904379', status: 'open', note: 'Board reversed the call' },
    ];
    for (const body of ok) {
      const r = await api.call('PUT', '/v1/admin/overrides', { token, body });
      assert.equal(r.status, 200, JSON.stringify(body));
    }
  });

  it('stores the days and ends the status when its last day ends in the zone', async () => {
    const token = await adminToken();
    // The days are named in the status's own zone, so this holds at any hour of the UTC day.
    const chicagoToday = localDate(Date.now(), 'America/Chicago');
    const days = [chicagoToday, addDays(chicagoToday, 1)];
    const r = await api.call('PUT', '/v1/admin/overrides', {
      token,
      body: {
        scope: 'district',
        id: '2700010',
        status: 'closed',
        days,
        time_zone: 'America/Chicago',
        expires_at: '2030-01-01T00:00:00Z',
      },
    });
    assert.equal(r.status, 200);
    const [row] = await api.sql("SELECT * FROM overrides WHERE key = 'district:2700010'");
    // A client's expiry is ignored: the Worker works it out from the last day.
    assert.equal(row.expires_at, endOfDay(days[1]!, 'America/Chicago'));
    assert.deepEqual(JSON.parse(row.days), days);
    assert.equal(row.time_zone, 'America/Chicago');
    assert.deepEqual(r.body.override.days, days);
    assert.equal(r.body.override.time_zone, 'America/Chicago');
    // Local midnight at the end of the last day.
    const end = new Date(row.expires_at);
    const hour = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/Chicago',
      hourCycle: 'h23',
      hour: '2-digit',
      minute: '2-digit',
    }).format(end);
    assert.equal(hour, '00:00');
    assert.equal(localDate(row.expires_at, 'America/Chicago'), addDays(days[1]!, 1));
  });

  it('works out the end of a day across a change of clocks', () => {
    // 2026-11-01: New York falls back from EDT (UTC-4) to EST (UTC-5).
    assert.equal(endOfDay('2026-10-31', ZONE), Date.parse('2026-11-01T04:00:00Z'));
    assert.equal(endOfDay('2026-11-01', ZONE), Date.parse('2026-11-02T05:00:00Z'));
    // 2027-03-14: springs forward.
    assert.equal(endOfDay('2027-03-14', ZONE), Date.parse('2027-03-15T04:00:00Z'));
    assert.equal(endOfDay('2026-12-31', 'Pacific/Honolulu'), Date.parse('2027-01-01T10:00:00Z'));
  });

  it('publishes only active overrides, with their days, without notes or who set them', async () => {
    const token = await adminToken();
    await api.call('PUT', '/v1/admin/overrides', {
      token,
      body: {
        scope: 'district',
        id: '1700001',
        status: 'delayed',
        minutes: 90,
        note: 'Called the office',
        days: [today(), tomorrow()],
        time_zone: ZONE,
      },
    });
    // Saving again replaces it: one row per target, with the new days and details.
    await api.call('PUT', '/v1/admin/overrides', {
      token,
      body: {
        scope: 'district',
        id: '1700001',
        status: 'closed',
        note: 'Called the office',
        days: [tomorrow()],
        time_zone: ZONE,
      },
    });
    await api.call('PUT', '/v1/admin/overrides', {
      token,
      body: {
        scope: 'district',
        id: '1700002',
        status: 'closed',
        days: [today()],
        time_zone: ZONE,
      },
    });
    await api.sql(
      "UPDATE overrides SET expires_at = ?1 WHERE key = 'district:1700002'",
      Date.now() - 1000,
    );
    const r = await api.call('GET', '/v1/overrides', { origin: null });
    assert.equal(r.status, 200);
    assert.equal(r.headers.get('Cache-Control'), 'public, max-age=30');
    const text = JSON.stringify(r.body);
    assert.ok(!text.includes('Called the office'));
    assert.ok(!text.includes('Olivia'));
    const rows = r.body.overrides.filter((o: { id: string }) => o.id.startsWith('17000'));
    assert.deepEqual(
      rows.map((o: { id: string; status: string; minutes: number | null; days: string[] }) => [
        o.id,
        o.status,
        o.minutes,
        o.days,
      ]),
      [['1700001', 'closed', null, [tomorrow()]]],
    );
    assert.deepEqual(Object.keys(rows[0]).sort(), [
      'at_local_time',
      'days',
      'expires_at',
      'id',
      'minutes',
      'scope',
      'set_at',
      'status',
      'time_zone',
    ]);
    assert.equal(rows[0].time_zone, ZONE);
    assert.equal(
      rows[0].expires_at,
      new Date(endOfDay(tomorrow(), ZONE)).toISOString().replace('.000Z', 'Z'),
    );
    assert.match(rows[0].expires_at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
    assert.match(r.body.generated_at, /Z$/);
    const adminList = await api.call('GET', '/v1/admin/overrides', { token });
    const mine = adminList.body.overrides.find(
      (o: { key: string }) => o.key === 'district:1700001',
    );
    assert.equal(mine.note, 'Called the office');
    assert.equal(mine.set_by, 'Olivia');
    assert.deepEqual(mine.days, [tomorrow()]);
    const expired = adminList.body.overrides.find(
      (o: { key: string }) => o.key === 'district:1700002',
    );
    assert.equal(expired.active, false);
    const log = await api.call('GET', '/v1/admin/audit', { token });
    const set = log.body.entries.find(
      (e: { action: string; target: string }) =>
        e.action === 'set_status' && e.target === 'district:1700001',
    );
    assert.deepEqual(set.detail.days, [tomorrow()]);
  });

  it('serves only the listed days that have not ended', async () => {
    const token = await adminToken();
    await api.call('PUT', '/v1/admin/overrides', {
      token,
      body: {
        scope: 'school',
        id: '170000100009',
        status: 'closed',
        days: [today(), tomorrow()],
        time_zone: ZONE,
      },
    });
    // As if it were set yesterday for yesterday and today: yesterday has ended.
    const yesterday = addDays(today(), -1);
    await api.sql(
      "UPDATE overrides SET days = ?1, expires_at = ?2 WHERE key = 'school:170000100009'",
      JSON.stringify([yesterday, today()]),
      endOfDay(today(), ZONE),
    );
    let r = await api.call('GET', '/v1/overrides');
    let row = r.body.overrides.find((o: { id: string }) => o.id === '170000100009');
    assert.deepEqual(row.days, [today()]);
    // Every listed day over: the row has expired, and is not served at all.
    await api.sql(
      "UPDATE overrides SET days = ?1, expires_at = ?2 WHERE key = 'school:170000100009'",
      JSON.stringify([yesterday]),
      endOfDay(yesterday, ZONE),
    );
    r = await api.call('GET', '/v1/overrides');
    row = r.body.overrides.find((o: { id: string }) => o.id === '170000100009');
    assert.equal(row, undefined);
  });

  it('serves a row written without days by its one day from its expiry', async () => {
    // Between migration 0002 and the deploy of this Worker, the Worker before days
    // can still write: a new row with no days, or a rewrite of a row whose days
    // then disagree with its new expiry. Each is served as the migration gives it.
    const expires = endOfDay(today(), ZONE) - 60_000; // 23:59 in New York, as v1 set it
    await api.sql(
      `INSERT INTO overrides (key, scope, target_id, status, set_at, expires_at)
       VALUES ('district:1700030', 'district', '1700030', 'closed', ?1, ?2)`,
      Date.now() - 60_000,
      expires,
    );
    await api.sql(
      `INSERT INTO overrides (key, scope, target_id, status, set_at, expires_at, days, time_zone)
       VALUES ('district:1700031', 'district', '1700031', 'closed', ?1, ?2, ?3, ?4)`,
      Date.now() - 60_000,
      expires,
      JSON.stringify([addDays(today(), -1)]),
      ZONE,
    );
    // A stored zone the runtime does not know, and days that are not a list of dates.
    await api.sql(
      `INSERT INTO overrides (key, scope, target_id, status, set_at, expires_at, days, time_zone)
       VALUES ('district:1700032', 'district', '1700032', 'closed', ?1, ?2, ?3, 'Mars/Olympus')`,
      Date.now() - 60_000,
      endOfDay(today(), ZONE),
      JSON.stringify([today()]),
    );
    await api.sql(
      `INSERT INTO overrides (key, scope, target_id, status, set_at, expires_at, days, time_zone)
       VALUES ('district:1700033', 'district', '1700033', 'closed', ?1, ?2, 'not json', ?3)`,
      Date.now() - 60_000,
      endOfDay(today(), ZONE),
      ZONE,
    );
    const r = await api.call('GET', '/v1/overrides');
    for (const id of ['1700030', '1700031', '1700032', '1700033']) {
      const served = r.body.overrides.find((o: { id: string }) => o.id === id);
      assert.deepEqual([id, served?.days, served?.time_zone], [id, [today()], null]);
    }
    const token = await adminToken();
    const list = await api.call('GET', '/v1/admin/overrides', { token });
    const mine = list.body.overrides.find((o: { key: string }) => o.key === 'district:1700030');
    assert.deepEqual([mine.days, mine.active], [[today()], true]);
  });

  it('gives an override set before days were stored its one day from its expiry', async () => {
    // Migration 0002 on a database holding a status the first admin form set:
    // "end of its day today", 23:59 in New York.
    const [y, m, d] = today().split('-').map(Number) as [number, number, number];
    const wall = Date.UTC(y, m - 1, d, 23, 59);
    const expires = wall + (endOfDay(today(), ZONE) - Date.UTC(y, m - 1, d + 1));
    await api.sql(
      `INSERT INTO overrides (key, scope, target_id, status, set_at, expires_at, days, time_zone)
       VALUES ('district:1700020', 'district', '1700020', 'closed', ?1, ?2, NULL, NULL)`,
      Date.now() - 60_000,
      expires,
    );
    const migration = readFileSync(
      new URL('../migrations/0002_override_days.sql', import.meta.url),
      'utf8',
    );
    const update = migration.split('\n').find((line) => line.startsWith('UPDATE overrides'))!;
    await api.sql(update.replace(/;$/, ''));
    const [row] = await api.sql(
      "SELECT days, time_zone FROM overrides WHERE key = 'district:1700020'",
    );
    assert.deepEqual(JSON.parse(row.days), [today()]);
    assert.equal(row.time_zone, null);
    const r = await api.call('GET', '/v1/overrides');
    const served = r.body.overrides.find((o: { id: string }) => o.id === '1700020');
    assert.deepEqual(served.days, [today()]);
    assert.equal(served.time_zone, null);
  });

  it('clears an override', async () => {
    const token = await adminToken();
    await api.call('PUT', '/v1/admin/overrides', {
      token,
      body: {
        scope: 'school',
        id: '170000100001',
        status: 'closed',
        days: [today()],
        time_zone: ZONE,
      },
    });
    const cleared = await api.call(
      'DELETE',
      `/v1/admin/overrides/${encodeURIComponent('school:170000100001')}`,
      { token },
    );
    assert.equal(cleared.status, 200);
    const again = await api.call('DELETE', '/v1/admin/overrides/school:170000100001', { token });
    assert.equal(again.status, 404);
    const r = await api.call('GET', '/v1/overrides');
    assert.ok(!r.body.overrides.some((o: { id: string }) => o.id === '170000100001'));
  });
});
