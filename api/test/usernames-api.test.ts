import assert from 'node:assert/strict';
import { createHash, createHmac } from 'node:crypto';
import { after, before, describe, it } from 'node:test';

import { BLOCKLIST } from '../src/usernames/blocklist.ts';
import { MAX_ADMIN_TERMS } from '../src/usernames/check.ts';
import { ADMIN_KEY, fakeKey, startApi, type Api } from './harness.ts';

/** Sign-ups a day from one network (account.ts SIGNUP_NETWORK_LIMIT). */
const SIGNUP_NETWORK_LIMIT = 20;

let api: Api;
let ipCounter = 0;
const ip = () => `192.0.2.${++ipCounter % 250}`;
let saltCounter = 0;
/** A client salt the browser would send: base64url of 16 bytes. */
const salt = () => Buffer.alloc(16, ++saltCounter).toString('base64url');
const legacy = (login: string) =>
  createHash('sha256').update(`snowlight-v1|${login}`).digest('base64url');

before(async () => {
  api = await startApi();
});
after(async () => {
  await api.close();
});

/** A sign-up from this version of the browser: both keys, their salts and a username. */
async function signup(
  username: string,
  email = `${username}@example.com`,
  password = 'pw',
  from = `198.18.${++ipCounter % 250}.1`,
) {
  // The email key's client salt is always the email's v1 salt.
  const emailSalt = legacy(email.trim().toLowerCase());
  const nameSalt = salt();
  const r = await api.call('POST', '/v1/signup', {
    ip: from,
    body: {
      name: 'Sam',
      email,
      username,
      over13: true,
      key: fakeKey(`${password}|${emailSalt}`),
      email_salt: emailSalt,
      name_key: fakeKey(`${password}|${nameSalt}`),
      name_salt: nameSalt,
    },
  });
  return { r, emailSalt, nameSalt };
}

async function loginWith(login: string, password = 'pw') {
  const s = await api.call('POST', '/v1/login/salt', { body: { login }, ip: ip() });
  assert.equal(s.status, 200);
  return api.call('POST', '/v1/login', {
    body: { login, key: fakeKey(`${password}|${s.body.salt}`) },
    ip: ip(),
  });
}

async function adminToken(): Promise<string> {
  const r = await api.call('POST', '/v1/login', {
    body: { login: 'olivia', key: ADMIN_KEY },
    ip: ip(),
  });
  assert.equal(r.status, 200);
  return r.body.token;
}

/** Every match of a moderation scan, page by page. */
async function scanAll(token: string, query = ''): Promise<string[]> {
  const names: string[] = [];
  let after = '';
  for (;;) {
    const r = await api.call('GET', `/v1/admin/moderation/scan?${query}&after=${after}`, { token });
    assert.equal(r.status, 200);
    names.push(...r.body.matches.map((m: { username: string }) => m.username));
    if (r.body.next === null) return names.sort();
    after = r.body.next;
  }
}

/** Every text value in every table, to show an erased email or name is gone. */
async function everything(): Promise<string> {
  const tables = await api.sql(
    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%' AND name != 'd1_migrations'",
  );
  let all = '';
  for (const { name } of tables) all += JSON.stringify(await api.sql(`SELECT * FROM ${name}`));
  return all;
}

describe('sign up with a username and a join number', () => {
  it('gives the admin #0001 and its login as its username', async () => {
    await adminToken();
    const [row] = await api.sql("SELECT username, join_number FROM users WHERE role = 'admin'");
    assert.deepEqual(row, { username: 'olivia', join_number: 1 });
  });

  it('numbers accounts in sign-up order from #0002 and shows the username', async () => {
    const { r } = await signup('frosty_fox');
    assert.equal(r.status, 201);
    assert.equal(r.body.user.username, 'frosty_fox');
    assert.equal(r.body.user.join_number, 2);
    assert.equal(r.body.user.username_required, false);
    assert.equal(r.body.user.needs_rekey, false);
  });

  it('refuses a taken username in any case, a reserved one and a blocked one', async () => {
    assert.equal((await signup('Frosty_Fox', 'other@example.com')).r.body.error, 'username_taken');
    assert.equal((await signup('0livia', 'o@example.com')).r.body.error, 'username_reserved');
    assert.equal((await signup('the_admin', 'a@example.com')).r.body.error, 'username_reserved');
    const term = BLOCKLIST.substring.find((t) => t.length >= 4 && t.length <= 8)!;
    assert.equal((await signup(`x${term}x`, 'b@example.com')).r.body.error, 'username_blocked');
    assert.equal((await signup('ab', 'c@example.com')).r.body.error, 'username_length');
    const [{ n }] = await api.sql("SELECT value AS n FROM counters WHERE name = 'join'");
    assert.equal(n, 2, 'a refused sign-up uses up no number');
  });

  it('never gives two sign-ups at once the same number', async () => {
    const results = await Promise.all(Array.from({ length: 12 }, (_, i) => signup(`racer_${i}`)));
    const numbers = results.map(({ r }) => r.body.user.join_number).sort((a, b) => a - b);
    assert.deepEqual(
      numbers,
      Array.from({ length: 12 }, (_, i) => 3 + i),
    );
  });

  it('gives #9998 and #9999 once each to sign-ups at the same moment, and the rest none', async () => {
    const [{ value: before }] = await api.sql("SELECT value FROM counters WHERE name = 'join'");
    await api.sql("UPDATE counters SET value = 9997 WHERE name = 'join'");
    const results = await Promise.all(Array.from({ length: 8 }, (_, i) => signup(`edge_${i}`)));
    assert.ok(results.every(({ r }) => r.status === 201));
    const numbers = results.map(({ r }) => r.body.user.join_number);
    assert.deepEqual(numbers.filter((n) => n !== null).sort(), [9998, 9999]);
    assert.equal(numbers.filter((n) => n === null).length, 6);
    const [{ value }] = await api.sql("SELECT value FROM counters WHERE name = 'join'");
    assert.equal(value, 9999);
    // Test only: free the two numbers again for the tests after this one.
    await api.sql("DELETE FROM users WHERE username GLOB 'edge_[0-9]'");
    await api.sql("UPDATE counters SET value = ?1 WHERE name = 'join'", before);
  });

  it('retires a deleted account number and stops after #9999', async () => {
    const { r, emailSalt } = await signup('leaving_soon');
    const number = r.body.user.join_number;
    const del = await api.call('DELETE', '/v1/me', {
      token: r.body.token,
      body: { key: fakeKey(`pw|${emailSalt}`) },
    });
    assert.equal(del.status, 200);
    assert.equal((await signup('next_one')).r.body.user.join_number, number + 1);
    await api.sql("UPDATE counters SET value = 9998 WHERE name = 'join'");
    assert.equal((await signup('last_og')).r.body.user.join_number, 9999);
    const late = await signup('too_late');
    assert.equal(late.r.status, 201);
    assert.equal(late.r.body.user.join_number, null);
    // Back to a low number for the tests after this one (no account holds 100-9998).
    await api.sql("UPDATE counters SET value = 100 WHERE name = 'join'");
  });
});

describe('sign-ups from one network', () => {
  for (const [kind, address] of [
    ['IPv6 /64', (i: number) => `2001:db8:1:2::${(i + 1).toString(16)}`],
    ['IPv4 /24', (i: number) => `203.0.113.${i + 1}`],
  ] as const)
    it(`are limited to ${SIGNUP_NETWORK_LIMIT} a day across every address of one ${kind}, and listed for the admin`, async () => {
      const results = [];
      for (let i = 0; i < SIGNUP_NETWORK_LIMIT + 3; i++)
        results.push(
          (
            await signup(
              `net${kind.includes('6') ? 'six' : 'four'}_${i}`,
              undefined,
              'pw',
              address(i),
            )
          ).r.status,
        );
      assert.deepEqual(results, [...Array<number>(SIGNUP_NETWORK_LIMIT).fill(201), 429, 429, 429]);
      // Another network is not held back.
      const other = kind === 'IPv4 /24' ? '203.0.114.1' : '2001:db8:1:3::1';
      assert.equal(
        (await signup(`net${kind.includes('6') ? 'six' : 'four'}_other`, undefined, 'pw', other)).r
          .status,
        201,
      );
      const summary = await api.call('GET', '/v1/admin/summary', { token: await adminToken() });
      const network = kind === 'IPv4 /24' ? '203.0.113.0/24' : '2001:db8:1:2::/64';
      const listed = summary.body.busy_networks.find(
        (n: { network: string }) => n.network === network,
      );
      assert.equal(listed.count, SIGNUP_NETWORK_LIMIT);
      assert.match(listed.day, /^\d{4}-\d{2}-\d{2}$/);
      // A network with one sign-up is not listed.
      assert.ok(
        !summary.body.busy_networks.some(
          (n: { network: string }) => n.network === other.replace(/\.1$/, '.0/24'),
        ),
      );
    });
});

describe('an account the old Worker made without a number', () => {
  it('gets the next number at its next login, once, and none when the numbers are used up', async () => {
    const { r } = await signup('gap_gus', 'gus@example.com');
    const { r: other } = await signup('gap_gil', 'gil@example.com');
    await api.sql(
      'UPDATE users SET join_number = NULL, numbered = 0 WHERE id IN (?1, ?2)',
      r.body.user.id,
      other.body.user.id,
    );
    const [{ value }] = await api.sql("SELECT value FROM counters WHERE name = 'join'");
    const [a, b] = await Promise.all([loginWith('gap_gus'), loginWith('gap_gil')]);
    assert.deepEqual([a.body.user.join_number, b.body.user.join_number].sort(), [
      value + 1,
      value + 2,
    ]);
    assert.equal((await loginWith('gap_gus')).body.user.join_number, a.body.user.join_number);
    const [{ value: after }] = await api.sql("SELECT value FROM counters WHERE name = 'join'");
    assert.equal(after, value + 2);
    // Past #9999 nothing is handed out, and the counter does not move.
    await api.sql(
      'UPDATE users SET join_number = NULL, numbered = 0 WHERE id = ?1',
      r.body.user.id,
    );
    await api.sql("UPDATE counters SET value = 9999 WHERE name = 'join'");
    assert.equal((await loginWith('gap_gus')).body.user.join_number, null);
    const [{ value: still }] = await api.sql("SELECT value FROM counters WHERE name = 'join'");
    assert.equal(still, 9999);
    await api.sql("UPDATE counters SET value = ?1 WHERE name = 'join'", after);
  });

  it('gets none when #9999 was given and its account deleted, and never one later', async () => {
    const [{ value: before }] = await api.sql("SELECT value FROM counters WHERE name = 'join'");
    const { r: old } = await signup('gap_gwen', 'gwen@example.com');
    await api.sql(
      'UPDATE users SET join_number = NULL, numbered = 0 WHERE id = ?1',
      old.body.user.id,
    );
    // Test only: #9999 free again (an earlier test gave it out), and the counter just below it.
    await api.sql('DELETE FROM users WHERE join_number = 9999');
    await api.sql("UPDATE counters SET value = 9998 WHERE name = 'join'");
    const last = await signup('last_lou', 'lou@example.com');
    assert.equal(last.r.body.user.join_number, 9999);
    const del = await api.call('DELETE', '/v1/me', {
      token: last.r.body.token,
      body: { key: fakeKey(`pw|${last.emailSalt}`) },
    });
    assert.equal(del.status, 200);
    const login = await loginWith('gap_gwen');
    assert.equal(login.status, 200);
    assert.equal(login.body.user.join_number, null);
    const [{ value }] = await api.sql("SELECT value FROM counters WHERE name = 'join'");
    assert.equal(value, 9999);
    assert.deepEqual(await api.sql('SELECT id FROM users WHERE join_number = 9999'), []);
    // It found none left, so it keeps none, even if the counter were ever lower (it never is).
    await api.sql("UPDATE counters SET value = ?1 WHERE name = 'join'", before);
    assert.equal((await loginWith('gap_gwen')).body.user.join_number, null);
    // So does an account that signed up after the last number.
    await api.sql("UPDATE counters SET value = 9999 WHERE name = 'join'");
    const late = await signup('late_lena', 'lena@example.com');
    assert.equal(late.r.body.user.join_number, null);
    await api.sql("UPDATE counters SET value = ?1 WHERE name = 'join'", before);
    assert.equal((await loginWith('late_lena')).body.user.join_number, null);
    const [{ value: still }] = await api.sql("SELECT value FROM counters WHERE name = 'join'");
    assert.equal(still, before);
  });

  it('gets none past #9999 even when it took the number given last, and logs in', async () => {
    // The order the parallel logins above end in, made certain: this account
    // takes the last number given, then is asked again with none left.
    const [{ value: before }] = await api.sql("SELECT value FROM counters WHERE name = 'join'");
    await api.sql("UPDATE counters SET value = 9998 WHERE name = 'join'");
    const top = await signup('top_tia', 'tia@example.com');
    assert.equal(top.r.body.user.join_number, 9999);
    await api.sql("UPDATE counters SET value = ?1 WHERE name = 'join'", before);
    const { r } = await signup('gap_gia', 'gia@example.com');
    assert.equal(r.body.user.join_number, before + 1);
    const forget = () =>
      api.sql('UPDATE users SET join_number = NULL, numbered = 0 WHERE id = ?1', r.body.user.id);
    await forget();
    assert.equal((await loginWith('gap_gia')).body.user.join_number, before + 2);
    await forget();
    await api.sql("UPDATE counters SET value = 9999 WHERE name = 'join'");
    const login = await loginWith('gap_gia');
    assert.equal(login.status, 200);
    assert.equal(login.body.user.join_number, null);
    const [{ value, holder }] = await api.sql(
      "SELECT value, holder FROM counters WHERE name = 'join'",
    );
    assert.equal(value, 9999);
    assert.equal(holder, null);
    assert.deepEqual(await api.sql('SELECT id FROM users WHERE join_number = 9999'), [
      { id: top.r.body.user.id },
    ]);
    // Test only: #9999 free again, and the counter where the numbers given left it.
    await api.sql('DELETE FROM users WHERE id = ?1', top.r.body.user.id);
    await api.sql("UPDATE counters SET value = ?1 WHERE name = 'join'", before + 2);
  });
});

describe('log in by username or email', () => {
  it('works with either, each with its own salt', async () => {
    const { emailSalt, nameSalt } = await signup('snow_owl', 'owl@example.com', 'hunter22');
    const byEmail = await api.call('POST', '/v1/login/salt', {
      body: { login: 'OWL@example.com' },
    });
    const byName = await api.call('POST', '/v1/login/salt', { body: { login: 'Snow_Owl' } });
    assert.equal(byEmail.body.salt, emailSalt);
    assert.equal(byName.body.salt, nameSalt);
    assert.equal((await loginWith('owl@example.com', 'hunter22')).status, 200);
    const r = await loginWith('SNOW_OWL', 'hunter22');
    assert.equal(r.status, 200);
    assert.equal(r.body.user.username, 'snow_owl');
    assert.equal((await loginWith('snow_owl', 'wrong')).status, 401);
    // The email key does not open the username login.
    const cross = await api.call('POST', '/v1/login', {
      body: { login: 'snow_owl', key: fakeKey(`hunter22|${emailSalt}`) },
      ip: ip(),
    });
    assert.equal(cross.status, 401);
  });

  it('answers every email with its v1 salt, so the answer tells nothing', async () => {
    await signup('salty_sam', 'salty@example.com');
    // A v1 account (no username key yet) and an email with no account at all.
    const { r: old } = await signup('old_salt', 'old.salt@example.com');
    await api.sql(
      'UPDATE users SET email_salt = NULL, name_salt = NULL, name_key_salt = NULL, name_key_hash = NULL WHERE id = ?1',
      old.body.user.id,
    );
    for (const login of ['salty@example.com', 'old.salt@example.com', 'no.one@example.com']) {
      const r = await api.call('POST', '/v1/login/salt', { body: { login }, ip: ip() });
      assert.equal(r.status, 200);
      assert.equal(r.body.salt, legacy(login), login);
    }
  });

  it('answers an unknown username with a steady made-up salt from a secret of its own, and the admin with its v1 salt', async () => {
    const a = await api.call('POST', '/v1/login/salt', { body: { login: 'nobody_here' } });
    const b = await api.call('POST', '/v1/login/salt', { body: { login: 'nobody_here' } });
    const c = await api.call('POST', '/v1/login/salt', { body: { login: 'nobody_there' } });
    assert.equal(a.body.salt, b.body.salt);
    assert.match(a.body.salt, /^[A-Za-z0-9_-]{22}$/);
    assert.notEqual(a.body.salt, c.body.salt);
    // Keyed on the migration's random secret, not on the admin's password.
    const [{ value }] = await api.sql("SELECT value FROM settings WHERE name = 'salt_secret'");
    assert.match(value, /^[0-9a-f]{64}$/);
    const expected = createHmac('sha256', value).update('nobody_here').digest().subarray(0, 16);
    assert.equal(a.body.salt, Buffer.from(expected).toString('base64url'));
    const admin = await api.call('POST', '/v1/login/salt', { body: { login: 'Olivia' } });
    assert.equal(admin.body.salt, legacy('olivia'));
  });

  it('limits salt requests per address', async () => {
    const address = '203.0.113.77';
    for (let i = 0; i < 30; i++) {
      const r = await api.call('POST', '/v1/login/salt', { body: { login: `x${i}` }, ip: address });
      assert.equal(r.status, 200);
    }
    const r = await api.call('POST', '/v1/login/salt', { body: { login: 'x' }, ip: address });
    assert.equal(r.status, 429);
  });

  it('keeps the email login open when anyone uses up the username login budget', async () => {
    await signup('budget_bob', 'bob@example.com');
    // Anyone can see a username: wrong tries by it from many addresses.
    for (let i = 0; i < 11; i++) await loginWith('budget_bob', 'nope');
    assert.equal((await loginWith('budget_bob', 'pw')).status, 429);
    assert.equal((await loginWith('bob@example.com', 'pw')).status, 200);
    // Wrong tries by email have their own budget.
    await signup('budget_bea', 'bea@example.com');
    for (let i = 0; i < 11; i++) await loginWith('bea@example.com', 'nope');
    assert.equal((await loginWith('bea@example.com', 'pw')).status, 429);
    assert.equal((await loginWith('budget_bea', 'pw')).status, 200);
  });

  it('drops the username key when a v1 browser changes the password', async () => {
    const { r, emailSalt } = await signup('old_browser', 'ob@example.com', 'first-pass');
    const change = await api.call('PATCH', '/v1/me', {
      token: r.body.token,
      body: {
        current_key: fakeKey(`first-pass|${emailSalt}`),
        new_key: fakeKey(`second-pass|${legacy('ob@example.com')}`),
      },
    });
    assert.equal(change.status, 200);
    assert.equal(change.body.user.needs_rekey, true);
    assert.equal((await loginWith('old_browser', 'first-pass')).status, 401);
  });
});

describe('a v1 account', () => {
  it('cannot be made any more: a sign-up without both keys and a username is from an old page', async () => {
    const v1 = await api.call('POST', '/v1/signup', {
      ip: ip(),
      body: {
        name: 'Vee',
        email: 'vee.old@example.com',
        key: fakeKey(`pw|${legacy('vee.old@example.com')}`),
        over13: true,
      },
    });
    assert.equal(v1.status, 400);
    assert.equal(v1.body.error, 'old_version');
    assert.equal(
      (await api.sql("SELECT 1 FROM users WHERE login = 'vee.old@example.com'")).length,
      0,
    );
  });

  it('logs in by email, takes fresh keys, then picks a username', async () => {
    // An account made by the v1 Worker: an email key only (its salt was the email's v1
    // salt then too), no username, no number.
    const { r: made } = await signup('vee_made', 'vee@example.com');
    await api.sql(
      `UPDATE users SET email_salt = NULL, name_salt = NULL, name_key_salt = NULL,
         name_key_hash = NULL, username = NULL, join_number = NULL, numbered = 0 WHERE id = ?1`,
      made.body.user.id,
    );
    const [{ value: before }] = await api.sql("SELECT value FROM counters WHERE name = 'join'");
    const login = await loginWith('vee@example.com');
    assert.equal(login.status, 200);
    assert.equal(login.body.user.username_required, true);
    assert.equal(login.body.user.needs_rekey, true);
    // It had no join number (made between the migration and the new Worker): it gets the next one.
    assert.equal(login.body.user.join_number, before + 1);
    const early = await api.call('PUT', '/v1/me/username', {
      token: login.body.token,
      body: { username: 'vee_v1' },
    });
    assert.equal(early.body.error, 'needs_rekey');
    const emailSalt = legacy('vee@example.com');
    const nameSalt = salt();
    const wrongSalt = await api.call('PATCH', '/v1/me', {
      token: login.body.token,
      body: {
        current_key: fakeKey(`pw|${emailSalt}`),
        new_key: fakeKey(`pw|${emailSalt}`),
        email_salt: salt(),
        name_key: fakeKey(`pw|${nameSalt}`),
        name_salt: nameSalt,
      },
    });
    assert.equal(wrongSalt.body.error, 'bad_key');
    const rekey = await api.call('PATCH', '/v1/me', {
      token: login.body.token,
      body: {
        current_key: fakeKey(`pw|${legacy('vee@example.com')}`),
        new_key: fakeKey(`pw|${emailSalt}`),
        email_salt: emailSalt,
        name_key: fakeKey(`pw|${nameSalt}`),
        name_salt: nameSalt,
      },
    });
    assert.equal(rekey.status, 200);
    assert.equal(rekey.body.user.needs_rekey, false);
    const pick = await api.call('PUT', '/v1/me/username', {
      token: rekey.body.token,
      body: { username: 'Vee_V1' },
    });
    assert.equal(pick.status, 200);
    assert.equal(pick.body.user.username, 'vee_v1');
    assert.equal(pick.body.user.username_required, false);
    assert.equal((await loginWith('vee_v1')).status, 200);
    const again = await api.call('PUT', '/v1/me/username', {
      token: rekey.body.token,
      body: { username: 'vee_two' },
    });
    assert.equal(again.body.error, 'username_set');
  });
});

describe('the live username check', () => {
  it('says free, taken, reserved or blocked', async () => {
    const free = await api.call('GET', '/v1/usernames/check?name=Brand_New_Name');
    assert.deepEqual(free.body, { ok: true, username: 'brand_new_name' });
    assert.deepEqual((await api.call('GET', '/v1/usernames/check?name=frosty_fox')).body, {
      ok: false,
      problem: 'username_taken',
    });
    assert.equal(
      (await api.call('GET', '/v1/usernames/check?name=admin')).body.problem,
      'username_reserved',
    );
    assert.equal(
      (await api.call('GET', '/v1/usernames/check?name=player_0042')).body.problem,
      'username_reserved',
    );
  });
});

describe('the live username check, from one address', () => {
  it('is limited', async () => {
    const address = '203.0.113.88';
    for (let i = 0; i < 120; i++) {
      const r = await api.call('GET', `/v1/usernames/check?name=name_${i}`, { ip: address });
      assert.equal(r.status, 200);
    }
    const r = await api.call('GET', '/v1/usernames/check?name=one_more', { ip: address });
    assert.equal(r.status, 429);
  });
});

describe('moderation', () => {
  it('is for the admin only', async () => {
    const { r } = await signup('nosy_nora');
    for (const [method, path] of [
      ['GET', '/v1/admin/moderation'],
      ['POST', '/v1/admin/moderation/terms'],
      ['GET', '/v1/admin/moderation/scan'],
      ['POST', `/v1/admin/users/${r.body.user.id}/rename`],
    ] as const) {
      const res = await api.call(method, path, {
        token: r.body.token,
        body: method === 'GET' ? undefined : {},
      });
      assert.equal(res.status, 403, path);
    }
  });

  it('adds a term that applies at once, scans it, and removes it', async () => {
    const admin = await adminToken();
    await signup('glitter_bug');
    await signup('glitterati');
    await signup('g_l_1_t_t_e_r');
    const add = await api.call('POST', '/v1/admin/moderation/terms', {
      token: admin,
      body: { term: 'Glitter', kind: 'substring' },
    });
    assert.equal(add.status, 200);
    assert.equal((await signup('glitter_girl')).r.body.error, 'username_blocked');
    assert.deepEqual(await scanAll(admin, 'term=glitter&kind=substring'), [
      'g_l_1_t_t_e_r',
      'glitter_bug',
      'glitterati',
    ]);
    await api.call('POST', '/v1/admin/moderation/terms', {
      token: admin,
      body: { term: 'glitterati', kind: 'allow' },
    });
    assert.deepEqual(await scanAll(admin), ['g_l_1_t_t_e_r', 'glitter_bug']);
    const list = await api.call('GET', '/v1/admin/moderation', { token: admin });
    assert.equal(list.body.terms.length, 2);
    assert.equal(
      (await api.call('DELETE', '/v1/admin/moderation/terms/substring:glitter', { token: admin }))
        .status,
      200,
    );
    assert.equal((await signup('glitter_girl')).r.status, 201);
  });

  it('takes a number code, applied to names with underscores in it', async () => {
    const admin = await adminToken();
    await signup('snow_13_12');
    const add = await api.call('POST', '/v1/admin/moderation/terms', {
      token: admin,
      body: { term: '13_12', kind: 'raw' },
    });
    assert.deepEqual(add.body, { term: '1312', kind: 'raw' });
    assert.equal((await signup('frost1312')).r.body.error, 'username_blocked');
    assert.deepEqual(await scanAll(admin, 'term=1312&kind=raw'), ['snow_13_12']);
    assert.ok((await scanAll(admin)).includes('snow_13_12'));
    assert.equal(
      (await api.call('DELETE', '/v1/admin/moderation/terms/raw:1312', { token: admin })).status,
      200,
    );
  });

  it(`keeps at most ${MAX_ADMIN_TERMS} terms of a kind`, async () => {
    const admin = await adminToken();
    const terms = Array.from(
      { length: MAX_ADMIN_TERMS },
      (_, i) => `('zz${i.toString(26).replace(/\d/g, (d) => 'qrstuvwxyz'[+d]!)}', 'token', 1)`,
    );
    await api.sql(`INSERT INTO moderation_terms (term, kind, added_at) VALUES ${terms.join(',')}`);
    const more = await api.call('POST', '/v1/admin/moderation/terms', {
      token: admin,
      body: { term: 'onemore', kind: 'token' },
    });
    assert.equal(more.status, 400);
    assert.equal(more.body.error, 'too_many_terms');
    await api.sql("DELETE FROM moderation_terms WHERE kind = 'token'");
  });

  it('pages a scan over every username', async () => {
    const admin = await adminToken();
    const rows = Array.from(
      { length: 450 },
      (_, i) =>
        `('${'f'.repeat(16)}${i.toString(16).padStart(16, '0')}', 'p${i}@example.org', 'P', 'paged_${String(i).padStart(3, '0')}', ${1000 + i})`,
    );
    await api.sql(
      `INSERT INTO users (id, login, name, username, created_at) VALUES ${rows.join(',')}`,
    );
    let after = '';
    let matches = 0;
    let pages = 0;
    for (;;) {
      const r = await api.call(
        'GET',
        `/v1/admin/moderation/scan?term=paged&kind=substring&after=${after}`,
        { token: admin },
      );
      assert.equal(r.status, 200);
      matches += r.body.matches.length;
      pages++;
      if (r.body.next === null) break;
      after = r.body.next;
    }
    assert.equal(matches, 450);
    assert.ok(pages >= 3);
  });
});

describe('retroactive rename', () => {
  it('renames to player_<number>, asks for a new name at sign-in, and logs both names', async () => {
    const admin = await adminToken();
    const { r } = await signup('rude_dude');
    const id = r.body.user.id;
    const number = r.body.user.join_number;
    const rename = await api.call('POST', `/v1/admin/users/${id}/rename`, {
      token: admin,
      body: {},
    });
    assert.equal(rename.status, 200);
    assert.equal(rename.body.username, `player_${String(number).padStart(4, '0')}`);
    const me = await api.call('GET', '/v1/me', { token: r.body.token });
    assert.equal(me.body.user.username_required, true);
    assert.equal(me.body.user.renamed, true);
    const blocked = BLOCKLIST.substring.find((t) => t.length >= 4 && t.length <= 8)!;
    const bad = await api.call('PUT', '/v1/me/username', {
      token: r.body.token,
      body: { username: `${blocked}_x` },
    });
    assert.equal(bad.body.error, 'username_blocked');
    const pick = await api.call('PUT', '/v1/me/username', {
      token: r.body.token,
      body: { username: 'nice_dude' },
    });
    assert.equal(pick.status, 200);
    assert.equal(pick.body.user.renamed, false);
    const log = await api.call('GET', '/v1/admin/audit', { token: admin });
    const entry = log.body.entries.find((e: { action: string }) => e.action === 'rename_user');
    assert.equal(entry.target, id);
    assert.deepEqual(entry.detail, {
      from: 'rude_dude',
      to: rename.body.username,
      join_number: number,
    });
    assert.deepEqual(entry.target_user, { username: 'nice_dude', join_number: number });
  });

  it('takes a name the admin types, under the same rules', async () => {
    const admin = await adminToken();
    const { r } = await signup('meh_name');
    const id = r.body.user.id;
    assert.equal(
      (
        await api.call('POST', `/v1/admin/users/${id}/rename`, {
          token: admin,
          body: { username: 'frosty_fox' },
        })
      ).body.error,
      'username_taken',
    );
    const ok = await api.call('POST', `/v1/admin/users/${id}/rename`, {
      token: admin,
      body: { username: 'Calm_Name' },
    });
    assert.equal(ok.body.username, 'calm_name');
  });
});

describe('a name an admin rename took away', () => {
  /** Every spelling of `name` (letters, one underscore) the hold alone refuses: case, underscores, leet, repeats and any digits. */
  const spellings = (name: string) => [
    name,
    name.toUpperCase(),
    name.replace('_', ''),
    name.replace('e', '3'),
    name.replace(/([a-z])/, '$1$1'),
    ...Array.from({ length: 10 }, (_, d) => `${name}${d}`),
    ...Array.from({ length: 10 }, (_, d) => `${d}${name}`),
    `${name}_99`,
    `${name}_2010`,
    `${name.replace('_', '')}2010`,
    `${name.replace('e', '3')}7`,
    name.replace('_', '_1_'),
  ];
  /** The name with words around it: refused only through the word the rename blocks for everyone. */
  const affixed = (name: string) => [
    `x_${name}`,
    `${name}_x`,
    `the_${name}`,
    `the${name.replace('_', '')}`,
    `${name.replace('_', '')}lord`,
    `${name.replace('_', '')}_kid_7`,
    `zz${name.replace('_', '').replace('e', '3')}zz`,
  ];

  async function refusedEverywhere(token: string, name: string, errors: readonly string[]) {
    const pick = await api.call('PUT', '/v1/me/username', { token, body: { username: name } });
    assert.ok(errors.includes(pick.body.error), `${name}: ${pick.body.error}`);
    const other = await signup(name, `other.${name}@example.com`);
    assert.ok(errors.includes(other.r.body.error), `${name}: ${other.r.body.error}`);
    const check = await api.call('GET', `/v1/usernames/check?name=${name}`, { ip: ip() });
    assert.equal(check.body.ok, false, name);
    assert.ok(errors.includes(check.body.problem), `${name}: ${check.body.problem}`);
  }

  it('is never picked again, in any case or spelling or with digits, by that account or anyone', async () => {
    const admin = await adminToken();
    const { r } = await signup('mean_namex');
    const id = r.body.user.id;
    // Without blocking the word: the hold alone.
    const rename = await api.call('POST', `/v1/admin/users/${id}/rename`, {
      token: admin,
      body: { block: false },
    });
    assert.equal(rename.status, 200);
    assert.equal(rename.body.blocked, null);
    for (const name of spellings('mean_namex'))
      await refusedEverywhere(r.body.token, name, ['username_taken']);
    // The rename stands until the account picks a new name of its own.
    const me = await api.call('GET', '/v1/me', { token: r.body.token });
    assert.equal(me.body.user.username, rename.body.username);
    assert.equal(me.body.user.username_required, true);
    const pick = await api.call('PUT', '/v1/me/username', {
      token: r.body.token,
      body: { username: 'kind_namex' },
    });
    assert.equal(pick.status, 200);
  });

  it('with "Also block this word for everyone" (the default), refuses it with any affix, digits or spelling', async () => {
    const admin = await adminToken();
    const { r } = await signup('gross_guyz');
    const id = r.body.user.id;
    const rename = await api.call('POST', `/v1/admin/users/${id}/rename`, {
      token: admin,
      body: {},
    });
    assert.equal(rename.status, 200);
    assert.deepEqual(rename.body.blocked, { term: 'grosguyz', kind: 'substring' });
    assert.equal(rename.body.block_problem, null);
    for (const name of [...spellings('gross_guyz'), ...affixed('gross_guyz')])
      await refusedEverywhere(r.body.token, name, ['username_taken', 'username_blocked']);
    const terms = await api.call('GET', '/v1/admin/moderation', { token: admin });
    assert.ok(
      terms.body.terms.some(
        (t: { term: string; kind: string }) => t.term === 'grosguyz' && t.kind === 'substring',
      ),
    );
    const log = await api.call('GET', '/v1/admin/audit', { token: admin });
    assert.ok(
      log.body.entries.some(
        (e: { action: string; detail: unknown }) =>
          e.action === 'add_term' &&
          JSON.stringify(e.detail) === JSON.stringify({ term: 'grosguyz', kind: 'substring' }),
      ),
    );
    const pick = await api.call('PUT', '/v1/me/username', {
      token: r.body.token,
      body: { username: 'kind_guyz' },
    });
    assert.equal(pick.status, 200);
  });

  it('blocks a 3-letter name as a whole word, says when a name is too short or the list is full, and renames anyway', async () => {
    const admin = await adminToken();
    const three = await signup('zqx_99');
    const r3 = await api.call('POST', `/v1/admin/users/${three.r.body.user.id}/rename`, {
      token: admin,
      body: {},
    });
    assert.deepEqual(r3.body.blocked, { term: 'zqx', kind: 'token' });
    for (const name of ['zqx', 'myzqx', 'zqx_kid', 'zqxlord7'])
      await refusedEverywhere(three.r.body.token, name, ['username_taken', 'username_blocked']);
    assert.equal((await signup('zqxonium')).r.status, 201, 'a longer word holding it is free');
    const two = await signup('zq_77');
    const r2 = await api.call('POST', `/v1/admin/users/${two.r.body.user.id}/rename`, {
      token: admin,
      body: {},
    });
    assert.equal(r2.status, 200);
    assert.equal(r2.body.blocked, null);
    assert.equal(r2.body.block_problem, 'too_short');
    // 50 substring words already: the rename stands, the word is not added.
    const [{ n }] = await api.sql(
      "SELECT COUNT(*) AS n FROM moderation_terms WHERE kind = 'substring'",
    );
    for (let i = n; i < MAX_ADMIN_TERMS; i++)
      await api.sql(
        "INSERT INTO moderation_terms (term, kind, added_at) VALUES (?1, 'substring', 0)",
        `qjfill${String.fromCharCode(97 + Math.floor(i / 26))}${String.fromCharCode(97 + (i % 26))}`,
      );
    const full = await signup('fullhouse_kid');
    const rf = await api.call('POST', `/v1/admin/users/${full.r.body.user.id}/rename`, {
      token: admin,
      body: {},
    });
    assert.equal(rf.status, 200);
    assert.equal(rf.body.blocked, null);
    assert.equal(rf.body.block_problem, 'too_many_terms');
    assert.equal(
      (await api.call('GET', '/v1/me', { token: full.r.body.token })).body.user.username_required,
      true,
    );
    await api.sql("DELETE FROM moderation_terms WHERE term LIKE 'qjfill%'");
  });

  it('is held when the admin typed the new name too, and a name the admin gave is not held', async () => {
    const admin = await adminToken();
    const { r } = await signup('other_guyx');
    const id = r.body.user.id;
    const typed = await api.call('POST', `/v1/admin/users/${id}/rename`, {
      token: admin,
      body: { username: 'typed_namex', block: false },
    });
    assert.equal(typed.status, 200);
    const again = await api.call('PUT', '/v1/me/username', {
      token: r.body.token,
      body: { username: 'other_guyx' },
    });
    assert.equal(again.body.error, 'username_taken');
    // Renamed once more by the admin before it picked: the admin's own name is not held.
    await api.call('POST', `/v1/admin/users/${id}/rename`, { token: admin, body: {} });
    const pick = await api.call('PUT', '/v1/me/username', {
      token: r.body.token,
      body: { username: 'typed_namex' },
    });
    assert.equal(pick.status, 200);
    // The table keeps hashes only, never a name.
    const held = await api.sql('SELECT * FROM held_usernames');
    assert.ok(held.length >= 2);
    assert.ok(!JSON.stringify(held).includes('guy'));
  });

  it('leaves renamed accounts out of the whole-list scan until they pick', async () => {
    const admin = await adminToken();
    const { r } = await signup('scan_skipx');
    const rename = await api.call('POST', `/v1/admin/users/${r.body.user.id}/rename`, {
      token: admin,
      body: {},
    });
    const all = await scanAll(admin);
    assert.ok(!all.some((name) => name.startsWith('player_')), all.join(','));
    assert.ok(!all.includes(rename.body.username));
  });
});

describe('deleting an account leaves no email or name behind', () => {
  it('by the user', async () => {
    const admin = await adminToken();
    const { r, emailSalt } = await signup('gone_girl', 'gone.girl@example.com');
    const id = r.body.user.id;
    await api.call('PATCH', '/v1/me', { token: r.body.token, body: { name: 'Zelda Quintessa' } });
    await api.call('POST', `/v1/admin/users/${id}/disable`, { token: admin });
    await api.call('POST', `/v1/admin/users/${id}/enable`, { token: admin });
    // A v1 admin log entry named the account by its email.
    await api.sql(
      "INSERT INTO audit (at, action, target) VALUES (1, 'disable_user', 'gone.girl@example.com')",
    );
    await loginWith('gone.girl@example.com', 'wrong');
    const login = await loginWith('gone_girl');
    const del = await api.call('DELETE', '/v1/me', {
      token: login.body.token,
      body: { key: fakeKey(`pw|${emailSalt}`) },
    });
    assert.equal(del.status, 200);
    const all = await everything();
    assert.ok(!all.includes('gone.girl@example.com'), 'email gone');
    assert.ok(!all.includes('Zelda Quintessa'), 'name gone');
    const entries = await api.sql('SELECT target FROM audit WHERE target = ?1', id);
    assert.equal(entries.length, 3);
    // Its username is held for 30 days, in every spelling, so nobody passes for it at once.
    for (const name of ['gone_girl', 'GoneGirl', 'g0ne_girl'])
      assert.equal((await signup(name, `new.${name}@example.com`)).r.body.error, 'username_taken');
    await api.sql('UPDATE held_usernames SET until = 1 WHERE until IS NOT NULL');
    assert.equal((await signup('gone_girl', 'new.gone.girl@example.com')).r.status, 201);
  });

  it('by the admin, with the log keeping the username and number', async () => {
    const admin = await adminToken();
    const { r } = await signup('bye_bye', 'bye.bye@example.com');
    const id = r.body.user.id;
    await api.call('POST', `/v1/admin/users/${id}/disable`, { token: admin });
    const del = await api.call('DELETE', `/v1/admin/users/${id}`, { token: admin });
    assert.equal(del.status, 200);
    const all = await everything();
    assert.ok(!all.includes('bye.bye@example.com'));
    const log = await api.call('GET', '/v1/admin/audit', { token: admin });
    const entry = log.body.entries.find(
      (e: { action: string; target: string }) => e.action === 'delete_user' && e.target === id,
    );
    assert.deepEqual(entry.detail, { username: 'bye_bye', join_number: r.body.user.join_number });
    assert.equal(entry.target_user, null);
  });
});

describe('migration 0003 on a v1 database', () => {
  it('numbers accounts by sign-up time, makes the admin #0001, and scrubs emails from the log', async () => {
    const v1 = await startApi({}, { skipMigrations: (file) => file >= '0003' });
    try {
      await v1.sql(
        `INSERT INTO users (id, login, email, name, role, created_at) VALUES
           ('${'a'.repeat(32)}', 'olivia', NULL, 'Olivia', 'admin', 50),
           ('${'b'.repeat(32)}', 'late@example.com', 'late@example.com', 'Late', 'user', 300),
           ('${'c'.repeat(32)}', 'early@example.com', 'early@example.com', 'Early', 'user', 100),
           ('${'d'.repeat(32)}', 'mid@example.com', 'mid@example.com', 'Mid', 'user', 200)`,
      );
      await v1.sql(
        `INSERT INTO audit (at, actor_id, actor_name, action, target) VALUES
           (1, NULL, 'Olivia', 'disable_user', 'mid@example.com'),
           (2, NULL, 'Olivia', 'delete_user', 'gone@example.com'),
           (3, NULL, 'Olivia', 'set_status', 'district:1234567')`,
      );
      await v1.migrate('0003_usernames.sql');
      const users = await v1.sql(
        'SELECT login, username, join_number FROM users ORDER BY join_number',
      );
      assert.deepEqual(users, [
        { login: 'olivia', username: 'olivia', join_number: 1 },
        { login: 'early@example.com', username: null, join_number: 2 },
        { login: 'mid@example.com', username: null, join_number: 3 },
        { login: 'late@example.com', username: null, join_number: 4 },
      ]);
      const audit = await v1.sql('SELECT target FROM audit ORDER BY id');
      assert.deepEqual(
        audit.map((a) => a.target),
        ['d'.repeat(32), 'deleted user', 'district:1234567'],
      );
      const [{ value }] = await v1.sql("SELECT value FROM counters WHERE name = 'join'");
      assert.equal(value, 4);
      // Every account there was is numbered: none is offered a number again at login.
      assert.deepEqual(await v1.sql('SELECT DISTINCT numbered FROM users'), [{ numbered: 1 }]);
      assert.deepEqual(await v1.sql('SELECT * FROM signup_networks'), []);
    } finally {
      await v1.close();
    }
  });
});
