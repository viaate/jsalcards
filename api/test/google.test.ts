/**
 * Connect Google (api/src/google.ts) against a local mock of Google's endpoints: the Worker's own
 * fetches go to `outbound` here, never to Google. The dormant path (no client configured) and the
 * configured one, state and PKCE, the encrypted token, the calendar import, the alert email,
 * disconnect and account deletion.
 */
import assert from 'node:assert/strict';
import { createHash, randomBytes } from 'node:crypto';
import { after, before, describe, it } from 'node:test';
import { fakeKey, startApi, ORIGIN, type Api } from './harness.ts';
import { signupOn } from './signup.ts';

const CLIENT_ID = '1234-test.apps.googleusercontent.com';
const CLIENT_SECRET = 'test-client-secret';

interface Seen {
  calls: { url: string; form: URLSearchParams | null; auth: string | null; body: string }[];
  challenges: Map<string, string>;
  revoked: Set<string>;
  /** Each refresh token's Google account (its sub): Google's revoke ends that account's grant. */
  owners: Map<string, string>;
  nextRefresh: number;
  email: string;
  /** The Google account's sub; null: one per address (as most tests need). */
  sub: string | null;
  /** Scopes Google adds to the code flow's answer (a grant left from the Gmail demo). */
  extraScope: string;
  /** Scopes Google adds to a refresh's answer. */
  refreshScope: string;
  /** How long Google takes to answer a code (ms), and a refresh. */
  codeDelay: number;
  refreshDelay: number;
}

const seen: Seen = {
  calls: [],
  challenges: new Map(),
  revoked: new Set(),
  owners: new Map(),
  nextRefresh: 0,
  email: 'pat@example.com',
  sub: null,
  extraScope: '',
  refreshScope: '',
  codeDelay: 0,
  refreshDelay: 0,
};
const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const GMAIL_READ = 'https://www.googleapis.com/auth/gmail.readonly';

/** The Google account the mock signs in as: a set sub, else one per address. */
function subNow(): string {
  return seen.sub ?? `sub-${seen.email.toLowerCase()}`;
}

function idToken(email: string, verified = true): string {
  const part = (value: object) => Buffer.from(JSON.stringify(value)).toString('base64url');
  return `${part({ alg: 'RS256' })}.${part({ email, email_verified: verified, sub: subNow() })}.sig`;
}

const jsonResponse = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

/** The mock: Google's token, revoke, calendar and Gmail send endpoints, checking what they get. */
async function google(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const body = request.method === 'POST' ? await request.text() : '';
  const form = request.headers.get('Content-Type')?.includes('form')
    ? new URLSearchParams(body)
    : null;
  seen.calls.push({
    url: `${url.origin}${url.pathname}`,
    form,
    auth: request.headers.get('Authorization'),
    body,
  });
  if (url.href.startsWith('https://oauth2.googleapis.com/token')) {
    if (form?.get('client_id') !== CLIENT_ID || form.get('client_secret') !== CLIENT_SECRET)
      return jsonResponse(401, { error: 'invalid_client' });
    if (form.get('grant_type') === 'authorization_code') {
      const code = form.get('code') ?? '';
      const challenge = seen.challenges.get(code);
      const verifier = form.get('code_verifier') ?? '';
      const made = createHash('sha256').update(verifier).digest('base64url');
      if (challenge === undefined || challenge !== made)
        return jsonResponse(400, { error: 'invalid_grant' });
      if (form.get('redirect_uri') !== `${ORIGIN}/google.html`)
        return jsonResponse(400, { error: 'redirect_uri_mismatch' });
      await wait(seen.codeDelay);
      seen.nextRefresh += 1;
      seen.owners.set(`refresh-${seen.nextRefresh}`, subNow());
      return jsonResponse(200, {
        access_token: 'access-a',
        refresh_token: `refresh-${seen.nextRefresh}`,
        id_token: idToken(seen.email),
        scope: `openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/gmail.send email${seen.extraScope}`,
        expires_in: 3599,
      });
    }
    if (form.get('grant_type') === 'refresh_token') {
      const token = form.get('refresh_token') ?? '';
      await wait(seen.refreshDelay);
      if (seen.revoked.has(token) || !token.startsWith('refresh-'))
        return jsonResponse(400, { error: 'invalid_grant' });
      return jsonResponse(200, {
        access_token: `access-for-${token}`,
        expires_in: 3599,
        scope: `https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/gmail.send${seen.refreshScope}`,
      });
    }
    return jsonResponse(400, { error: 'unsupported_grant_type' });
  }
  if (url.href.startsWith('https://oauth2.googleapis.com/revoke')) {
    // As Google does: the whole grant of that Google account ends, every token of it (GIS:
    // "revokes all of the scopes that the user granted to the app"). A later consent is a new one.
    const token = form?.get('token') ?? '';
    seen.revoked.add(token);
    const owner = seen.owners.get(token);
    for (const [other, sub] of seen.owners)
      if (owner !== undefined && sub === owner) seen.revoked.add(other);
    return new Response('', { status: 200 });
  }
  if (url.href.startsWith('https://www.googleapis.com/calendar/v3/calendars/primary/events')) {
    if (!request.headers.get('Authorization')?.startsWith('Bearer access-for-refresh-'))
      return jsonResponse(401, {});
    return jsonResponse(200, {
      items: [
        {
          summary: 'Flight to Los Angeles (WN 1234)',
          location: 'Kansas City MCI',
          start: { dateTime: '2026-11-25T06:10:00-06:00', timeZone: 'America/Chicago' },
          end: { dateTime: '2026-11-25T07:50:00-08:00' },
        },
        { summary: 'Dentist', start: { dateTime: '2026-11-26T09:00:00-06:00' } },
        { summary: `Flight home ${'x'.repeat(5000)}`, start: { date: '2026-11-27' } },
      ],
    });
  }
  if (url.href.startsWith('https://gmail.googleapis.com/gmail/v1/users/me/messages/send')) {
    if (!request.headers.get('Authorization')?.startsWith('Bearer access-for-refresh-'))
      return jsonResponse(401, {});
    return jsonResponse(200, { id: 'm1' });
  }
  return new Response('not mocked', { status: 599 });
}

let dormant: Api;
let api: Api;
let demo: Api;
let sameClient: Api;
let counter = 100;
const DEMO_CLIENT_ID = '5678-demo.apps.googleusercontent.com';

before(async () => {
  dormant = await startApi({}, { outbound: google });
  api = await startApi(
    { GOOGLE_CLIENT_ID: CLIENT_ID, GOOGLE_CLIENT_SECRET: CLIENT_SECRET },
    { outbound: google },
  );
  demo = await startApi(
    {
      GOOGLE_CLIENT_ID: CLIENT_ID,
      GOOGLE_CLIENT_SECRET: CLIENT_SECRET,
      GMAIL_READ_DEMO: '1',
      GMAIL_DEMO_CLIENT_ID: DEMO_CLIENT_ID,
    },
    { outbound: google },
  );
  sameClient = await startApi(
    {
      GOOGLE_CLIENT_ID: CLIENT_ID,
      GOOGLE_CLIENT_SECRET: CLIENT_SECRET,
      GMAIL_READ_DEMO: '1',
      GMAIL_DEMO_CLIENT_ID: CLIENT_ID,
    },
    { outbound: google },
  );
});
after(async () => {
  await Promise.all([dormant.close(), api.close(), demo.close(), sameClient.close()]);
});

/** A new account, and a Google account of its own for the mock (each person has their own). */
const signup = (target: Api = api) => {
  counter += 1;
  seen.email = `pat${String(counter)}@example.com`;
  return signupOn(target, 'goog', counter);
};

/** Starts a connect and plays Google's part: the code it would send back, tied to the challenge. */
async function startAndAuthorize(
  target: Api,
  token: string,
): Promise<{ code: string; state: string; url: URL }> {
  const r = await target.call('POST', '/v1/me/google/start', { token, body: {} });
  assert.equal(r.status, 200, JSON.stringify(r.body));
  const url = new URL(r.body.url);
  const code = `code-${Buffer.from(randomBytes(6)).toString('hex')}`;
  seen.challenges.set(code, url.searchParams.get('code_challenge') ?? '');
  return { code, state: url.searchParams.get('state') ?? '', url };
}

async function connect(target: Api, token: string): Promise<void> {
  const { code, state } = await startAndAuthorize(target, token);
  const r = await target.call('POST', '/v1/me/google/finish', { token, body: { code, state } });
  assert.equal(r.status, 200, JSON.stringify(r.body));
}

/** The sender's key, written as the Actions sender writes it: its SHA-256 and its end. */
async function senderKey(target: Api, ends = Date.now() + 600_000): Promise<string> {
  const key = Buffer.from(randomBytes(32)).toString('base64url');
  const digest = createHash('sha256').update(key).digest('hex');
  await target.sql(
    "INSERT INTO settings (name, value) VALUES ('flights_mail_key', ?1) ON CONFLICT (name) DO UPDATE SET value = ?1",
    `${digest}:${ends}`,
  );
  return key;
}

function alert(trip = '0123456789abcdef0123456789abcdef') {
  return {
    v: 1,
    kind: 'flight',
    alert: 'chance',
    trip,
    carrier: 'WN',
    number: 1234,
    from: 'MCI',
    to: 'LAX',
    day: '2026-11-25',
    leaves: 370,
    cancel: 35,
    late: 20,
    level: 'cancel',
    why: 0,
    faa: null,
    waiver: null,
    backups: [
      {
        carrier: 'WN',
        number: 1500,
        from: 'MCI',
        to: 'LAX',
        day: '2026-11-25',
        leaves: 545,
        // Hours from now, whenever the test runs: the email names only backups still to catch.
        departs: Math.floor(Date.now() / 1000) + 6 * 3600,
        chance: 84,
        via: null,
      },
    ],
    ticket: 'regular',
  };
}

describe('dormant until configured', () => {
  it('says not configured, shows no client id and no Gmail demo', async () => {
    const r = await dormant.call('GET', '/v1/google/config');
    assert.equal(r.status, 200);
    assert.deepEqual(r.body, {
      configured: false,
      client_id: null,
      gmail_demo: false,
      gmail_client_id: null,
    });
  });

  it('answers google_off on every Google route, and never calls Google', async () => {
    const before = seen.calls.length;
    const a = await signup(dormant);
    const me = await dormant.call('GET', '/v1/me/google', { token: a.token });
    assert.deepEqual(me.body, { configured: false, connected: false });
    for (const [method, path] of [
      ['POST', '/v1/me/google/start'],
      ['POST', '/v1/me/google/finish'],
      ['POST', '/v1/me/google/calendar'],
    ] as const) {
      const r = await dormant.call(method, path, {
        token: a.token,
        body: { code: 'c', state: 'x'.repeat(43) },
      });
      assert.equal(r.status, 404, path);
      assert.equal(r.body.error, 'google_off');
    }
    const key = await senderKey(dormant);
    const mail = await dormant.call('POST', '/v1/internal/flights/mail', {
      origin: null,
      headers: { Authorization: `Bearer ${key}` },
      body: { user_id: a.id, alert: alert() },
    });
    assert.equal(mail.status, 404);
    // Disconnect still answers (nothing to revoke), and deleting the account works as before.
    assert.equal((await dormant.call('DELETE', '/v1/me/google', { token: a.token })).status, 200);
    const del = await dormant.call('DELETE', '/v1/me', {
      token: a.token,
      body: { key: fakeKey(a.email) },
    });
    assert.equal(del.status, 200);
    assert.equal(seen.calls.length, before);
  });
});

describe('configured', () => {
  it('serves the client id, and the Gmail demo only where it is on with a client of its own', async () => {
    assert.deepEqual((await api.call('GET', '/v1/google/config')).body, {
      configured: true,
      client_id: CLIENT_ID,
      gmail_demo: false,
      gmail_client_id: null,
    });
    assert.deepEqual((await demo.call('GET', '/v1/google/config')).body, {
      configured: true,
      client_id: CLIENT_ID,
      gmail_demo: true,
      gmail_client_id: DEMO_CLIENT_ID,
    });
    // SAFE-R2-S1: never on Connect Google's own client, whose grant the demo's revoke would end.
    const same = (await sameClient.call('GET', '/v1/google/config')).body;
    assert.equal(same.gmail_demo, false);
    assert.equal(same.gmail_client_id, null);
  });

  it('starts with a fresh state and an S256 challenge, keeping only the state’s hash', async () => {
    const a = await signup();
    const { url, state } = await startAndAuthorize(api, a.token);
    assert.equal(url.origin + url.pathname, 'https://accounts.google.com/o/oauth2/v2/auth');
    const p = url.searchParams;
    assert.equal(p.get('client_id'), CLIENT_ID);
    assert.equal(p.get('redirect_uri'), `${ORIGIN}/google.html`);
    assert.equal(p.get('response_type'), 'code');
    assert.equal(p.get('code_challenge_method'), 'S256');
    assert.match(p.get('code_challenge') ?? '', /^[A-Za-z0-9_-]{43}$/);
    assert.equal(p.get('access_type'), 'offline');
    // Never a grant given elsewhere (the Gmail demo's gmail.readonly) folded into this token.
    assert.equal(p.get('include_granted_scopes'), null);
    assert.deepEqual((p.get('scope') ?? '').split(' ').sort(), [
      'email',
      'https://www.googleapis.com/auth/calendar.readonly',
      'https://www.googleapis.com/auth/gmail.send',
      'openid',
    ]);
    assert.match(state, /^[A-Za-z0-9_-]{43}$/);
    const rows = await api.sql(
      'SELECT state_hash, verifier FROM google_states WHERE user_id = ?1',
      a.id,
    );
    assert.equal(rows.length, 1);
    assert.notEqual(rows[0].state_hash, state);
    assert.equal(rows[0].state_hash, createHash('sha256').update(state).digest('base64url'));
    assert.equal(
      createHash('sha256').update(rows[0].verifier).digest('base64url'),
      p.get('code_challenge'),
    );
  });

  it('returns to the site’s own base path, and refuses one that does not read', async () => {
    const a = await signup();
    const r = await api.call('POST', '/v1/me/google/start', {
      token: a.token,
      body: { base: '/repo/' },
    });
    assert.equal(
      new URL(r.body.url).searchParams.get('redirect_uri'),
      `${ORIGIN}/repo/google.html`,
    );
    for (const base of ['repo/', '//evil.example/', '/a/../b/', 'https://evil.example/']) {
      const bad = await api.call('POST', '/v1/me/google/start', { token: a.token, body: { base } });
      assert.equal(bad.status, 400, base);
    }
  });

  it('refuses a start from a site that is not ours', async () => {
    const a = await signup();
    const r = await api.call('POST', '/v1/me/google/start', {
      token: a.token,
      body: {},
      origin: 'https://evil.example',
    });
    assert.equal(r.status, 403);
  });

  it('finishes only for the account that started it, once, within 10 minutes', async () => {
    const a = await signup();
    const b = await signup();
    // Someone else's connect: refused, and gone.
    const theirs = await startAndAuthorize(api, a.token);
    const stolen = await api.call('POST', '/v1/me/google/finish', { token: b.token, body: theirs });
    assert.equal(stolen.status, 400);
    assert.equal(stolen.body.error, 'bad_state');
    const late = await api.call('POST', '/v1/me/google/finish', { token: a.token, body: theirs });
    assert.equal(late.status, 400);
    assert.deepEqual(
      await api.sql('SELECT * FROM google_links WHERE user_id IN (?1, ?2)', a.id, b.id),
      [],
    );
    // Expired.
    const old = await startAndAuthorize(api, a.token);
    await api.sql('UPDATE google_states SET expires_at = 1 WHERE user_id = ?1', a.id);
    assert.equal(
      (await api.call('POST', '/v1/me/google/finish', { token: a.token, body: old })).status,
      400,
    );
    // A code with the wrong verifier (Google's PKCE check) is refused by Google, so here too.
    const wrong = await startAndAuthorize(api, a.token);
    seen.challenges.set(wrong.code, 'not-the-challenge');
    const pk = await api.call('POST', '/v1/me/google/finish', { token: a.token, body: wrong });
    assert.equal(pk.status, 502);
    // The right one: connected, and used once.
    const good = await startAndAuthorize(api, a.token);
    const done = await api.call('POST', '/v1/me/google/finish', { token: a.token, body: good });
    assert.equal(done.status, 200);
    assert.equal(typeof done.body.since, 'number');
    assert.deepEqual(done.body, {
      configured: true,
      connected: true,
      email: seen.email,
      calendar: true,
      send: true,
      since: done.body.since,
    });
    assert.equal(
      (await api.call('POST', '/v1/me/google/finish', { token: a.token, body: good })).status,
      400,
    );
    const me = await api.call('GET', '/v1/me/google', { token: a.token });
    assert.equal(me.body.connected, true);
    assert.equal(me.body.email, seen.email);
    assert.equal(me.body.since, done.body.since);
  });

  it('keeps the refresh token only encrypted, and bound to its account', async () => {
    const a = await signup();
    const b = await signup();
    await connect(api, a.token);
    const [row] = await api.sql(
      'SELECT refresh_token, scopes FROM google_links WHERE user_id = ?1',
      a.id,
    );
    assert.match(row.refresh_token, /^v1\.[A-Za-z0-9_-]{16}\.[A-Za-z0-9_-]+$/);
    assert.ok(!row.refresh_token.includes('refresh-'));
    assert.ok(!JSON.stringify(await api.sql('SELECT * FROM google_links')).includes('"refresh-'));
    // Copied to another account, it does not open there: that account reads as disconnected.
    await api.sql(
      "INSERT INTO google_links (user_id, google_email, scopes, refresh_token, connected_at) VALUES (?1, 'b@example.com', ?2, ?3, 1)",
      b.id,
      row.scopes,
      row.refresh_token,
    );
    const r = await api.call('POST', '/v1/me/google/calendar', { token: b.token });
    assert.equal(r.status, 409);
    assert.equal(r.body.error, 'google_revoked');
    assert.deepEqual(await api.sql('SELECT * FROM google_links WHERE user_id = ?1', b.id), []);
  });

  it('brings in calendar events that read like flights, cut short, and keeps none of them', async () => {
    const a = await signup();
    assert.equal(
      (await api.call('POST', '/v1/me/google/calendar', { token: a.token })).status,
      404,
    );
    await connect(api, a.token);
    const r = await api.call('POST', '/v1/me/google/calendar', { token: a.token });
    assert.equal(r.status, 200, JSON.stringify(r.body));
    assert.equal(r.body.events.length, 2);
    assert.equal(r.body.events[0].summary, 'Flight to Los Angeles (WN 1234)');
    assert.equal(r.body.events[0].start, '2026-11-25T06:10:00-06:00');
    assert.equal(r.body.events[0].zone, 'America/Chicago');
    assert.ok(r.body.events[1].summary.length <= 200);
    const call = [...seen.calls].reverse().find((c) => c.url.includes('/calendar/'));
    assert.ok(call);
    const tables = await api.sql("SELECT name FROM sqlite_master WHERE type = 'table'");
    for (const { name } of tables) {
      if (name.startsWith('_') || name.startsWith('sqlite')) continue;
      const dump = JSON.stringify(await api.sql(`SELECT * FROM ${name}`));
      assert.ok(!dump.includes('Los Angeles'), name);
    }
  });

  it('reads a token Google no longer takes as disconnected', async () => {
    const a = await signup();
    await connect(api, a.token);
    seen.revoked.add(`refresh-${seen.nextRefresh}`);
    const r = await api.call('POST', '/v1/me/google/calendar', { token: a.token });
    assert.equal(r.status, 409);
    assert.equal(
      (await api.call('GET', '/v1/me/google', { token: a.token })).body.connected,
      false,
    );
  });

  it('refuses a token that can read Gmail: revoked at Google, nothing kept', async () => {
    const a = await signup();
    seen.extraScope = ` ${GMAIL_READ}`;
    try {
      const { code, state } = await startAndAuthorize(api, a.token);
      const r = await api.call('POST', '/v1/me/google/finish', {
        token: a.token,
        body: { code, state },
      });
      assert.equal(r.status, 502);
      assert.equal(r.body.error, 'google_scopes');
      assert.ok(seen.revoked.has(`refresh-${seen.nextRefresh}`));
      assert.deepEqual(await api.sql('SELECT * FROM google_links WHERE user_id = ?1', a.id), []);
      assert.equal(
        (await api.call('GET', '/v1/me/google', { token: a.token })).body.connected,
        false,
      );
    } finally {
      seen.extraScope = '';
    }
  });

  it('a reconnect that answers with a Gmail read scope ends the old link of that Google account too', async () => {
    // SAFE-R2-B1: the revoke ends the Google account's whole grant, the stored link's token with
    // it, so that link is gone too and Google reads as disconnected, never connected on a dead
    // grant. Another Snowlight account linked to the same Google account ends with it; a link to
    // another Google account stays.
    const other = await signup();
    await connect(api, other.token);
    const elsewhere = await signup();
    await connect(api, elsewhere.token);
    const a = await signup();
    await connect(api, a.token);
    const old = `refresh-${seen.nextRefresh}`;
    const b = await signup();
    seen.email = (
      await api.sql('SELECT google_email FROM google_links WHERE user_id = ?1', a.id)
    )[0].google_email;
    await connect(api, b.token);
    seen.extraScope = ` ${GMAIL_READ}`;
    try {
      const { code, state } = await startAndAuthorize(api, a.token);
      const r = await api.call('POST', '/v1/me/google/finish', {
        token: a.token,
        body: { code, state },
      });
      assert.equal(r.status, 502);
      assert.equal(r.body.error, 'google_scopes');
    } finally {
      seen.extraScope = '';
    }
    assert.ok(seen.revoked.has(old));
    for (const account of [a, b]) {
      assert.deepEqual(
        await api.sql('SELECT * FROM google_links WHERE user_id = ?1', account.id),
        [],
      );
      assert.deepEqual((await api.call('GET', '/v1/me/google', { token: account.token })).body, {
        configured: true,
        connected: false,
      });
    }
    for (const account of [other, elsewhere])
      assert.equal(
        (await api.call('GET', '/v1/me/google', { token: account.token })).body.connected,
        true,
      );
    assert.equal(
      (await api.call('POST', '/v1/me/google/calendar', { token: other.token })).status,
      200,
    );
  });

  it('a disconnect never ends another Snowlight account’s link to the same Google account', async () => {
    // SAFE-R2-S1: one grant per Google account; while another account holds a link to it, the
    // token is deleted here but not revoked (that would end the other link too).
    const a = await signup();
    await connect(api, a.token);
    const b = await signup();
    seen.email = (
      await api.sql('SELECT google_email FROM google_links WHERE user_id = ?1', a.id)
    )[0].google_email;
    await connect(api, b.token);
    const before = seen.calls.filter((c) => c.url.endsWith('/revoke')).length;
    assert.equal((await api.call('DELETE', '/v1/me/google', { token: a.token })).status, 200);
    assert.equal(seen.calls.filter((c) => c.url.endsWith('/revoke')).length, before);
    assert.deepEqual(await api.sql('SELECT * FROM google_links WHERE user_id = ?1', a.id), []);
    assert.equal(
      (await api.call('POST', '/v1/me/google/calendar', { token: b.token })).status,
      200,
    );
    // The last link to it: revoked at Google as before.
    const token = `refresh-${seen.nextRefresh}`;
    assert.equal((await api.call('DELETE', '/v1/me/google', { token: b.token })).status, 200);
    assert.ok(seen.revoked.has(token));
  });

  it('knows a Google account by its sub: a renamed address is the same one, a reused one is not', async () => {
    // SAFE-R3-S1: Google ties a grant to the account (the ID token's sub), not to its email.
    const revokes = () => seen.calls.filter((c) => c.url.endsWith('/revoke')).length;
    const a = await signup();
    seen.sub = `sub-renamed-${String(counter)}`;
    try {
      await connect(api, a.token);
      assert.equal(
        (await api.sql('SELECT google_sub FROM google_links WHERE user_id = ?1', a.id))[0]
          .google_sub,
        seen.sub,
      );
      // The same Google account under a new address, linked by another Snowlight account.
      const b = await signup();
      await connect(api, b.token);
      const before = revokes();
      assert.equal((await api.call('DELETE', '/v1/me/google', { token: a.token })).status, 200);
      assert.equal(revokes(), before);
      assert.equal(
        (await api.call('POST', '/v1/me/google/calendar', { token: b.token })).status,
        200,
      );
      // A reused address on another Google account: a refused reconnect of the first ends only
      // its own links, and the other stays connected and working.
      const c = await signup();
      seen.sub = `sub-first-${String(counter)}`;
      await connect(api, c.token);
      const reused = seen.email;
      const d = await signup();
      seen.email = reused;
      seen.sub = `sub-second-${String(counter)}`;
      await connect(api, d.token);
      seen.sub = `sub-first-${String(counter - 1)}`;
      seen.extraScope = ` ${GMAIL_READ}`;
      try {
        const { code, state } = await startAndAuthorize(api, c.token);
        const r = await api.call('POST', '/v1/me/google/finish', {
          token: c.token,
          body: { code, state },
        });
        assert.equal(r.body.error, 'google_scopes');
      } finally {
        seen.extraScope = '';
      }
      assert.equal(
        (await api.call('GET', '/v1/me/google', { token: c.token })).body.connected,
        false,
      );
      assert.equal(
        (await api.call('GET', '/v1/me/google', { token: d.token })).body.connected,
        true,
      );
      assert.equal(
        (await api.call('POST', '/v1/me/google/calendar', { token: d.token })).status,
        200,
      );
      // A link kept with no sub is matched by its address.
      await api.sql('UPDATE google_links SET google_sub = NULL WHERE user_id = ?1', d.id);
      const e = await signup();
      seen.email = reused;
      seen.sub = `sub-third-${String(counter)}`;
      await connect(api, e.token);
      const held = revokes();
      assert.equal((await api.call('DELETE', '/v1/me/google', { token: e.token })).status, 200);
      assert.equal(revokes(), held);
    } finally {
      seen.sub = null;
    }
  });

  it('asks Google about a link near Testing mode’s 7 days when the page reads it', async () => {
    // SAFE-R3-S2: never connected with email on, on a token Google has ended.
    const tokenCalls = () =>
      seen.calls.filter(
        (c) => c.url.endsWith('/token') && c.form?.get('grant_type') === 'refresh_token',
      ).length;
    const a = await signup();
    await connect(api, a.token);
    const token = `refresh-${seen.nextRefresh}`;
    // A fresh link is read from here alone.
    let calls = tokenCalls();
    assert.equal((await api.call('GET', '/v1/me/google', { token: a.token })).body.connected, true);
    assert.equal(tokenCalls(), calls);
    // Six days and more, not used lately: checked once, then not again for a while.
    await api.sql(
      'UPDATE google_links SET connected_at = connected_at - ?2 WHERE user_id = ?1',
      a.id,
      7 * 86_400_000,
    );
    assert.equal((await api.call('GET', '/v1/me/google', { token: a.token })).body.connected, true);
    assert.equal(tokenCalls(), calls + 1);
    calls = tokenCalls();
    assert.equal((await api.call('GET', '/v1/me/google', { token: a.token })).body.connected, true);
    assert.equal(tokenCalls(), calls);
    // Google ended it (as Testing mode does on day 7): the page reads disconnected.
    seen.revoked.add(token);
    await api.sql(
      'UPDATE google_links SET used_at = used_at - ?2 WHERE user_id = ?1',
      a.id,
      7 * 3_600_000,
    );
    assert.deepEqual((await api.call('GET', '/v1/me/google', { token: a.token })).body, {
      configured: true,
      connected: false,
    });
    assert.deepEqual(await api.sql('SELECT * FROM google_links WHERE user_id = ?1', a.id), []);
  });

  it('a reconnect sent while the page checks an old link keeps the new link, whatever answers first', async () => {
    // SAFE-R4-B1: the page's read of an old link (its token ended on day 7) and the finish of a
    // new connect, at once. The dead token's drop never takes the new link or the waiting state,
    // and the read answers from the row as it is after Google answers it.
    const cases = [
      { refresh: 0, code: 0, lag: 0 },
      { refresh: 60, code: 20, lag: 0 },
      { refresh: 200, code: 20, lag: 0 },
      { refresh: 0, code: 20, lag: 30 },
      { refresh: 20, code: 0, lag: 0 },
      // A day-6 token that still works: the read never answers with the old row's day.
      { refresh: 60, code: 20, lag: 0, live: true },
      { refresh: 0, code: 20, lag: 30, live: true },
    ];
    for (const one of cases) {
      const a = await signup();
      await connect(api, a.token);
      if (one.live !== true) seen.revoked.add(`refresh-${seen.nextRefresh}`);
      await api.sql(
        'UPDATE google_links SET connected_at = connected_at - ?2, used_at = NULL WHERE user_id = ?1',
        a.id,
        7 * 86_400_000,
      );
      const { code, state } = await startAndAuthorize(api, a.token);
      seen.refreshDelay = one.refresh;
      seen.codeDelay = one.code;
      const started = Date.now();
      try {
        let readAt = 0;
        let finishAt = Infinity;
        const [read, finish] = await Promise.all([
          api.call('GET', '/v1/me/google', { token: a.token }).then((answer) => {
            readAt = performance.now();
            return answer;
          }),
          wait(one.lag).then(() => {
            finishAt = performance.now();
            return api.call('POST', '/v1/me/google/finish', {
              token: a.token,
              body: { code, state },
            });
          }),
        ]);
        const label = JSON.stringify(one);
        assert.equal(finish.status, 200, `${label} ${JSON.stringify(finish.body)}`);
        const fresh = `refresh-${seen.nextRefresh}`;
        assert.equal(seen.revoked.has(fresh), false, label);
        const rows = await api.sql(
          'SELECT connected_at FROM google_links WHERE user_id = ?1',
          a.id,
        );
        assert.equal(rows.length, 1, label);
        assert.ok(rows[0].connected_at >= started, label);
        // A read still open when the finish was sent says connected only with the new link's
        // day, never the old one's.
        if (read.body.connected === true && readAt > finishAt)
          assert.ok(read.body.since >= started, label);
        const after = await api.call('GET', '/v1/me/google', { token: a.token });
        assert.equal(after.body.connected, true, label);
        assert.equal(after.body.since, rows[0].connected_at, label);
      } finally {
        seen.refreshDelay = 0;
        seen.codeDelay = 0;
      }
    }
  });

  it('never uses a refresh that answers with a Gmail read scope: revoked, and shown disconnected', async () => {
    const a = await signup();
    await connect(api, a.token);
    const token = `refresh-${seen.nextRefresh}`;
    seen.refreshScope = ` ${GMAIL_READ}`;
    try {
      const r = await api.call('POST', '/v1/me/google/calendar', { token: a.token });
      assert.equal(r.status, 409);
      assert.ok(seen.revoked.has(token));
      assert.ok(
        !seen.calls.some(
          (c) => c.url.includes('/calendar/v3/') && c.auth === `Bearer access-for-${token}`,
        ),
      );
      assert.equal(
        (await api.call('GET', '/v1/me/google', { token: a.token })).body.connected,
        false,
      );
    } finally {
      seen.refreshScope = '';
    }
  });

  it('connecting another Google account revokes the old grant; the same account keeps it', async () => {
    const a = await signup();
    await connect(api, a.token);
    const first = `refresh-${seen.nextRefresh}`;
    await connect(api, a.token);
    const second = `refresh-${seen.nextRefresh}`;
    assert.ok(!seen.revoked.has(first));
    const pat = seen.email;
    seen.email = `sam${String(counter)}@example.com`;
    try {
      await connect(api, a.token);
    } finally {
      seen.email = pat;
    }
    assert.ok(seen.revoked.has(second));
    assert.ok(!seen.revoked.has(`refresh-${seen.nextRefresh}`));
    const r = await api.call('GET', '/v1/me/google', { token: a.token });
    assert.equal(r.body.email, `sam${String(counter)}@example.com`);
    assert.equal(
      (await api.call('POST', '/v1/me/google/calendar', { token: a.token })).status,
      200,
    );
  });

  it('disconnects: Google is asked to revoke, and the link is gone', async () => {
    const a = await signup();
    await connect(api, a.token);
    const token = `refresh-${seen.nextRefresh}`;
    const r = await api.call('DELETE', '/v1/me/google', { token: a.token });
    assert.equal(r.status, 200);
    assert.ok(seen.revoked.has(token));
    assert.deepEqual(await api.sql('SELECT * FROM google_links WHERE user_id = ?1', a.id), []);
    assert.equal(
      (await api.call('GET', '/v1/me/google', { token: a.token })).body.connected,
      false,
    );
  });

  it('deleting the account revokes at Google and deletes the link and any connect', async () => {
    const a = await signup();
    await connect(api, a.token);
    const token = `refresh-${seen.nextRefresh}`;
    await startAndAuthorize(api, a.token);
    const r = await api.call('DELETE', '/v1/me', {
      token: a.token,
      body: { key: fakeKey(a.email) },
    });
    assert.equal(r.status, 200);
    assert.ok(seen.revoked.has(token));
    assert.deepEqual(await api.sql('SELECT * FROM google_links WHERE user_id = ?1', a.id), []);
    assert.deepEqual(await api.sql('SELECT * FROM google_states WHERE user_id = ?1', a.id), []);
  });

  it('sends the alert email from the person’s Gmail to themselves, only for the sender’s key', async () => {
    const a = await signup();
    const call = (key: string | null, body: unknown) =>
      api.call('POST', '/v1/internal/flights/mail', {
        origin: null,
        headers: key === null ? {} : { Authorization: `Bearer ${key}` },
        body,
      });
    const body = { user_id: a.id, alert: alert() };
    assert.equal((await call(null, body)).status, 401);
    assert.equal(
      (await call(Buffer.from(randomBytes(32)).toString('base64url'), body)).status,
      401,
    );
    const expired = await senderKey(api, Date.now() - 1000);
    assert.equal((await call(expired, body)).status, 401);
    const key = await senderKey(api);
    assert.equal((await call(key, body)).status, 404);
    await connect(api, a.token);
    assert.equal(
      (await call(key, { user_id: a.id, alert: { ...alert(), cancel: 250 } })).status,
      400,
    );
    const r = await call(key, body);
    assert.equal(r.status, 200, JSON.stringify(r.body));
    const sent = [...seen.calls].reverse().find((c) => c.url.includes('/messages/send'));
    assert.ok(sent);
    const raw = Buffer.from(JSON.parse(sent.body).raw, 'base64url').toString('utf8');
    assert.match(raw, new RegExp(`^From: Snowlight <${seen.email}>\r\nTo: ${seen.email}\r\n`));
    const subject = /Subject: =\?UTF-8\?B\?([^?]+)\?=/.exec(raw)?.[1] ?? '';
    assert.equal(
      Buffer.from(subject, 'base64').toString('utf8'),
      'WN 1234 · MCI to LAX: 35% chance of a cancel.',
    );
    const parts = raw.split(/\r\n\r\n/);
    const text = Buffer.from(
      (parts[2] ?? '').split('--snowlight')[0]!.replace(/\r\n/g, ''),
      'base64',
    ).toString('utf8');
    assert.match(text, /Safer: WN 1500 at 9:05 am, 84% chance to get there on time\./);
    assert.match(text, /We don’t see prices or seats\. Check with the airline before you switch\./);
    assert.match(text, /\?mode=flights&page=trips&trip=0123456789abcdef0123456789abcdef/);
  });
});
