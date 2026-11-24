import assert from 'node:assert/strict';
import { after, before, describe, it } from 'node:test';
import { fakeKey, startApi, type Api } from './harness.ts';
import { signupOn } from './signup.ts';

let api: Api;
let ipCounter = 0;
const ip = () => `198.19.${++ipCounter % 250}.7`;

before(async () => {
  api = await startApi();
});
after(async () => {
  await api.close();
});

let userCounter = 0;
const signup = () => signupOn(api, 'trips', ++userCounter);

/** A day `ahead` days from today (UTC), as the API reads trip days. */
function dayAhead(ahead: number): string {
  return new Date(Date.now() + ahead * 86_400_000).toISOString().slice(0, 10);
}

function trip(overrides: Record<string, unknown> = {}) {
  return {
    carrier: 'WN',
    number: 1234,
    from: 'MCI',
    to: 'LAX',
    day: dayAhead(2),
    leaves: 370,
    lands: 470,
    ...overrides,
  };
}

describe('trips', () => {
  it('needs a session', async () => {
    assert.equal((await api.call('GET', '/v1/me/trips')).status, 401);
    assert.equal((await api.call('POST', '/v1/me/trips', { body: trip() })).status, 401);
  });

  it('saves a flight, lists it, and keeps one trip for the same flight and day', async () => {
    const a = await signup();
    const r = await api.call('POST', '/v1/me/trips', { token: a.token, body: trip(), ip: ip() });
    assert.equal(r.status, 201, JSON.stringify(r.body));
    assert.match(r.body.trip.id, /^[0-9a-f]{32}$/);
    assert.equal(r.body.trip.ticket, 'unsure');
    assert.equal(r.body.trip.ticket_asked, false);
    assert.equal(r.body.trip.source, 'typed');
    // The same flight again with new times and a ticket type: one trip, updated.
    const again = await api.call('POST', '/v1/me/trips', {
      token: a.token,
      body: trip({ leaves: 380, ticket: 'basic', source: 'calendar' }),
    });
    assert.equal(again.status, 201);
    assert.equal(again.body.trip.id, r.body.trip.id);
    assert.equal(again.body.trip.leaves, 380);
    assert.equal(again.body.trip.ticket, 'basic');
    assert.equal(again.body.trip.ticket_asked, true);
    // Sent again without a ticket: the ticket type is kept.
    const kept = await api.call('POST', '/v1/me/trips', { token: a.token, body: trip() });
    assert.equal(kept.body.trip.ticket, 'basic');
    await api.call('POST', '/v1/me/trips', {
      token: a.token,
      body: trip({ number: 99, day: dayAhead(1), leaves: 600 }),
    });
    const list = await api.call('GET', '/v1/me/trips', { token: a.token });
    assert.equal(list.status, 200);
    assert.deepEqual(
      list.body.trips.map((t: { number: number }) => t.number),
      [99, 1234],
    );
  });

  it('refuses a trip that does not read', async () => {
    const a = await signup();
    const bad = [
      trip({ carrier: 'wn' }),
      trip({ carrier: 'WNA' }),
      trip({ number: 0 }),
      trip({ number: 10000 }),
      trip({ number: 12.5 }),
      trip({ from: 'MC' }),
      trip({ to: 'MCI' }),
      trip({ day: '2026-02-30' }),
      trip({ day: 'tomorrow' }),
      trip({ leaves: 1440 }),
      trip({ lands: -1 }),
      trip({ ticket: 'first' }),
      trip({ source: 'email' }),
      trip({ need_by: '2026-01-05 10:00' }),
    ];
    for (const body of bad) {
      const r = await api.call('POST', '/v1/me/trips', { token: a.token, body });
      assert.equal(r.status, 400, JSON.stringify(body));
    }
    const past = await api.call('POST', '/v1/me/trips', {
      token: a.token,
      body: trip({ day: dayAhead(-3) }),
    });
    assert.equal(past.status, 400);
    assert.equal(past.body.error, 'bad_day');
    const far = await api.call('POST', '/v1/me/trips', {
      token: a.token,
      body: trip({ day: dayAhead(400) }),
    });
    assert.equal(far.body.error, 'bad_day');
    assert.deepEqual((await api.call('GET', '/v1/me/trips', { token: a.token })).body.trips, []);
  });

  it('keeps up to 20 trips', async () => {
    const a = await signup();
    for (let n = 1; n <= 20; n++) {
      const r = await api.call('POST', '/v1/me/trips', {
        token: a.token,
        body: trip({ number: n }),
      });
      assert.equal(r.status, 201);
    }
    const over = await api.call('POST', '/v1/me/trips', {
      token: a.token,
      body: trip({ number: 21 }),
    });
    assert.equal(over.status, 409);
    assert.equal(over.body.error, 'too_many_trips');
    // The same flight as one kept still updates.
    const same = await api.call('POST', '/v1/me/trips', {
      token: a.token,
      body: trip({ number: 7, ticket: 'premium' }),
    });
    assert.equal(same.status, 201);
  });

  it('changes the ticket type and the need-by time, and marks the one tap shown', async () => {
    const a = await signup();
    const day = dayAhead(3);
    const made = (await api.call('POST', '/v1/me/trips', { token: a.token, body: trip({ day }) }))
      .body.trip;
    const skip = await api.call('PATCH', `/v1/me/trips/${made.id}`, {
      token: a.token,
      body: { ticket_asked: true },
    });
    assert.equal(skip.status, 200);
    assert.equal(skip.body.trip.ticket, 'unsure');
    assert.equal(skip.body.trip.ticket_asked, true);
    const later = await api.call('PATCH', `/v1/me/trips/${made.id}`, {
      token: a.token,
      body: { ticket: 'regular', need_by: `${day}T14:30` },
    });
    assert.equal(later.body.trip.ticket, 'regular');
    assert.equal(later.body.trip.need_by, `${day}T14:30`);
    for (const body of [
      { ticket: 'cheap' },
      { need_by: `${dayAhead(9)}T10:00` },
      { need_by: `${day}T25:00` },
      { seat: '12A' },
      { ticket_asked: false },
    ]) {
      const r = await api.call('PATCH', `/v1/me/trips/${made.id}`, { token: a.token, body });
      assert.equal(r.status, 400, JSON.stringify(body));
    }
    const cleared = await api.call('PATCH', `/v1/me/trips/${made.id}`, {
      token: a.token,
      body: { need_by: null },
    });
    assert.equal(cleared.body.trip.need_by, null);
  });

  it('never shows, changes or deletes another account’s trip', async () => {
    const a = await signup();
    const b = await signup();
    const made = (await api.call('POST', '/v1/me/trips', { token: a.token, body: trip() })).body
      .trip;
    assert.deepEqual((await api.call('GET', '/v1/me/trips', { token: b.token })).body.trips, []);
    const patch = await api.call('PATCH', `/v1/me/trips/${made.id}`, {
      token: b.token,
      body: { ticket: 'basic' },
    });
    assert.equal(patch.status, 404);
    const del = await api.call('DELETE', `/v1/me/trips/${made.id}`, { token: b.token });
    assert.equal(del.status, 404);
    assert.equal(
      (await api.call('GET', '/v1/me/trips', { token: a.token })).body.trips[0].ticket,
      'unsure',
    );
  });

  it('deletes a trip with what was sent for it', async () => {
    const a = await signup();
    const made = (await api.call('POST', '/v1/me/trips', { token: a.token, body: trip() })).body
      .trip;
    await api.sql(
      "INSERT INTO flights_sent (user_id, trip_id, kind, value, sent_at) VALUES (?1, ?2, 'chance', '30', 1)",
      a.id,
      made.id,
    );
    const r = await api.call('DELETE', `/v1/me/trips/${made.id}`, { token: a.token });
    assert.equal(r.status, 200);
    assert.deepEqual(await api.sql('SELECT * FROM trips WHERE id = ?1', made.id), []);
    assert.deepEqual(await api.sql('SELECT * FROM flights_sent WHERE trip_id = ?1', made.id), []);
    assert.equal(
      (await api.call('DELETE', `/v1/me/trips/${made.id}`, { token: a.token })).status,
      404,
    );
    assert.equal((await api.call('DELETE', '/v1/me/trips/nope', { token: a.token })).status, 404);
  });
});

describe('Flights alert choices', () => {
  it('starts at the defaults: on, 30%, the evening check on at 8 pm, email on', async () => {
    const a = await signup();
    const r = await api.call('GET', '/v1/me/flights/notify', { token: a.token });
    assert.deepEqual(r.body.settings, {
      alerts: true,
      threshold: 30,
      night_before: true,
      night_time: '20:00',
      email: true,
    });
  });

  it('changes any of them and refuses anything out of range', async () => {
    const a = await signup();
    const r = await api.call('PATCH', '/v1/me/flights/notify', {
      token: a.token,
      body: { threshold: 70, email: false, night_time: '19:30' },
    });
    assert.equal(r.status, 200);
    assert.equal(r.body.settings.threshold, 70);
    assert.equal(r.body.settings.email, false);
    for (const body of [
      { threshold: 40 },
      { alerts: 'yes' },
      { night_time: '08:00' },
      { night_time: '20:15' },
      { quiet: true },
    ]) {
      const bad = await api.call('PATCH', '/v1/me/flights/notify', { token: a.token, body });
      assert.equal(bad.status, 400, JSON.stringify(body));
    }
    const read = await api.call('GET', '/v1/me/flights/notify', { token: a.token });
    assert.equal(read.body.settings.night_time, '19:30');
  });
});

describe('account deletion and the daily sweep', () => {
  it('deleting the account removes its trips, its Flights choices and its sent log', async () => {
    const a = await signup();
    const made = (await api.call('POST', '/v1/me/trips', { token: a.token, body: trip() })).body
      .trip;
    await api.call('PATCH', '/v1/me/flights/notify', { token: a.token, body: { threshold: 50 } });
    await api.sql(
      "INSERT INTO flights_sent (user_id, trip_id, kind, value, sent_at) VALUES (?1, ?2, 'faa', 'MCI:0:1', 1)",
      a.id,
      made.id,
    );
    const r = await api.call('DELETE', '/v1/me', {
      token: a.token,
      body: { key: fakeKey(a.email) },
    });
    assert.equal(r.status, 200);
    for (const table of [
      'trips',
      'flights_notify',
      'flights_sent',
      'google_links',
      'google_states',
    ])
      assert.deepEqual(await api.sql(`SELECT * FROM ${table} WHERE user_id = ?1`, a.id), [], table);
  });

  it('drops trips two weeks past their day, and keeps the rest', async () => {
    const a = await signup();
    const kept = (await api.call('POST', '/v1/me/trips', { token: a.token, body: trip() })).body
      .trip;
    await api.sql(
      `INSERT INTO trips (id, user_id, carrier, number, from_airport, to_airport, day, leaves, lands, created_at, updated_at)
       VALUES ('0123456789abcdef0123456789abcdef', ?1, 'AA', 1, 'DFW', 'ORD', ?2, 400, 500, 1, 1)`,
      a.id,
      dayAhead(-20),
    );
    await api.sql(
      "INSERT INTO flights_sent (user_id, trip_id, kind, value, sent_at) VALUES (?1, '0123456789abcdef0123456789abcdef', 'chance', '30', 1)",
      a.id,
    );
    const worker: any = await api.mf.getWorker();
    await worker.scheduled({ scheduledTime: new Date(), cron: '23 8 * * *' });
    const ids = (await api.sql('SELECT id FROM trips WHERE user_id = ?1', a.id)).map(
      (row) => row.id,
    );
    assert.deepEqual(ids, [kept.id]);
    assert.deepEqual(await api.sql('SELECT * FROM flights_sent WHERE user_id = ?1', a.id), []);
  });
});
