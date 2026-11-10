import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { tick } from '../prober/src/tick.ts';
import { dayOf } from '../shared/history.ts';
import { DAY } from '../shared/types.ts';
import type { Summary } from '../shared/types.ts';
import {
  CLOSINGS_URL,
  Net,
  STAMP_URL,
  WHERE,
  closingsBody,
  healthy,
  startStore,
  stampBody,
} from './harness.ts';
import type { Store } from './harness.ts';

let store: Store;
before(async () => {
  store = await startStore();
});
after(async () => {
  await store.close();
});

/** Counts the statements a tick sends to D1: it sends each one it prepares exactly once. */
function counted(db: D1Database): { db: D1Database; statements: () => number } {
  let statements = 0;
  const wrapped = {
    prepare(query: string) {
      statements += 1;
      return db.prepare(query);
    },
    batch: (list: D1PreparedStatement[]) => db.batch(list),
  };
  return { db: wrapped as unknown as D1Database, statements: () => statements };
}

const T = Date.UTC(2026, 10, 10, 12, 0, 0) / 1000;
const net = (t: number): Net => healthy(new Net(t * 1000 + 2000));
const summaryOf = async (): Promise<Summary> =>
  JSON.parse(
    (await store.sql<{ v: string }>("SELECT v FROM meta WHERE k = 'summary'"))[0]!.v,
  ) as Summary;

test('a first tick on an empty store', async () => {
  const web = net(T);
  assert.equal(await tick({ ...WHERE, DB: store.db }, T, web), 'taken');
  assert.equal(web.calls.length, 4);
  const samples = await store.sql('SELECT * FROM samples');
  // The four parts are asked together, so the made-up clock gives each a time of its own.
  for (const key of ['site_ms', 'accounts_ms']) {
    assert.equal(typeof samples[0]![key], 'number');
    delete samples[0]![key];
  }
  assert.deepEqual(samples, [
    {
      t: T,
      site: 'ok',
      closings: 'ok',
      chances: 'ok',
      accounts: 'ok',
      site_code: 200,
      closings_code: 200,
      chances_code: 200,
      accounts_code: 200,
      closings_made: T + 2 - 200,
      chances_made: T + 2 - 600,
      closings_allow: 0,
      chances_allow: 0,
      closings_bytes: closingsBody(T * 1000, 0).length,
    },
  ]);
  assert.deepEqual(await store.sql("SELECT k, v FROM meta WHERE k <> 'summary' ORDER BY k"), [
    { k: 'first', v: String(T) },
    { k: 'processed', v: String(T) },
  ]);
  assert.deepEqual(
    await store.sql('SELECT part, ok, late, down FROM days WHERE day = ? ORDER BY part', dayOf(T)),
    [
      { part: 'accounts', ok: 1, late: 0, down: 0 },
      { part: 'chances', ok: 1, late: 0, down: 0 },
      { part: 'closings', ok: 1, late: 0, down: 0 },
      { part: 'site', ok: 1, late: 0, down: 0 },
    ],
  );
  const summary = await summaryOf();
  assert.deepEqual(Object.keys(summary), [
    'v',
    'now',
    'first',
    'parts',
    'from',
    'days',
    'incidents',
  ]);
  assert.deepEqual(summary.parts, {
    site: { s: 'ok' },
    closings: { s: 'ok', made: T + 2 - 200 },
    chances: { s: 'ok', made: T + 2 - 600 },
    accounts: { s: 'ok' },
  });
  assert.deepEqual(
    [summary.v, summary.now, summary.first, summary.from],
    [1, T, T, dayOf(T - 89 * DAY)],
  );
  assert.deepEqual(summary.incidents, []);
  assert.deepEqual(summary.days.site[89], [1, 0, 0]);
});

test('the same tick twice probes and writes once', async () => {
  const web = net(T);
  assert.equal(await tick({ ...WHERE, DB: store.db }, T, web), 'skipped');
  assert.equal(await tick({ ...WHERE, DB: store.db }, T - 300, web), 'skipped');
  assert.equal(web.calls.length, 0);
  assert.deepEqual(await store.sql('SELECT COUNT(*) AS n FROM samples'), [{ n: 1 }]);
  assert.deepEqual(
    await store.sql('SELECT ok FROM days WHERE day = ? AND part = ?', dayOf(T), 'site'),
    [{ ok: 1 }],
  );
});

test('trouble is kept: states, codes, an open problem, and l on open problems only', async () => {
  const web = new Net((T + 300) * 1000 + 2000)
    .on(WHERE.SITE_URL, { status: 200, ms: 4000 })
    .on(WHERE.ACCOUNTS_HEALTH_URL, 'none')
    .on(CLOSINGS_URL, { status: 404, body: 'gone' });
  web.on(STAMP_URL, { status: 200, body: stampBody(web.clock, 3000), headers: { age: '100' } });
  assert.equal(await tick({ ...WHERE, DB: store.db }, T + 300, web), 'taken');
  // All four parts are asked every tick; the website and accounts twice.
  assert.deepEqual(
    [...new Set(web.calls.map((call) => call.url))].sort(),
    [WHERE.ACCOUNTS_HEALTH_URL, CLOSINGS_URL, STAMP_URL, WHERE.SITE_URL].sort(),
  );
  assert.equal(web.calls.length, 6);
  const row = (await store.sql('SELECT * FROM samples WHERE t = ?', T + 300))[0]!;
  assert.deepEqual(
    [row['site'], row['closings'], row['chances'], row['accounts']],
    ['late', 'down', 'late', 'unknown'],
  );
  assert.deepEqual(
    [row['site_code'], row['closings_code'], row['chances_code'], row['accounts_code']],
    [200, 404, 200, 0],
  );
  assert.equal((row['site_ms'] as number) >= 4000, true);
  assert.deepEqual(
    [row['accounts_ms'], row['closings_bytes'], row['chances_allow']],
    [null, null, 100],
  );
  let summary = await summaryOf();
  assert.deepEqual(summary.parts.closings, { s: 'down' });
  assert.deepEqual(
    summary.incidents.map((i) => [i.p, i.k, i.s, i.e, i.g, i.l]),
    [
      ['site', 'late', T + 300, null, 0, T + 300],
      ['closings', 'down', T + 300, null, 0, T + 300],
      ['chances', 'late', T + 300, null, 0, T + 300],
    ],
  );
  // The next tick all is well: each is closed, and a closed problem carries no `l`.
  assert.equal(await tick({ ...WHERE, DB: store.db }, T + 600, net(T + 600)), 'taken');
  summary = await summaryOf();
  assert.deepEqual(summary.incidents, [
    { p: 'site', k: 'late', s: T + 300, e: T + 600, g: 0 },
    { p: 'closings', k: 'down', s: T + 300, e: T + 600, g: 0 },
    { p: 'chances', k: 'late', s: T + 300, e: T + 600, g: 0 },
  ]);
  assert.deepEqual(summary.days.site[89], [2, 1, 0]);
  assert.deepEqual(summary.days.accounts[89], [2, 0, 0]);
  assert.deepEqual(await store.sql('SELECT COUNT(*) AS n FROM incidents'), [{ n: 3 }]);
  assert.equal(summary.first, T);
});

test('a tick sends 25 statements at most, even its worst', async () => {
  // Every part has an open problem whose readings stopped, and is bad again, on a new UTC day.
  const next = T + DAY;
  await store.sql(
    "INSERT INTO incidents (part, kind, start, last, ended, gap) VALUES ('site','down',?1,?1,NULL,0), ('closings','down',?1,?1,NULL,0), ('chances','down',?1,?1,NULL,0), ('accounts','down',?1,?1,NULL,0)",
    T + 900,
  );
  const web = new Net(next * 1000 + 2000)
    .on(WHERE.SITE_URL, { status: 500 })
    .on(WHERE.ACCOUNTS_HEALTH_URL, { status: 500 })
    .on(CLOSINGS_URL, { status: 500 })
    .on(STAMP_URL, { status: 500 });
  const watch = counted(store.db);
  assert.equal(await tick({ ...WHERE, DB: watch.db }, next, web), 'taken');
  assert.equal(web.calls.length, 8);
  assert.equal(watch.statements() <= 25, true, String(watch.statements()));
  // The stored values, two reads, the sample, 4 days, 4 problems closed where the readings
  // stopped, 4 opened, the tick, the summary and the day's 3 deletes.
  assert.equal(watch.statements(), 21);
  const summary = await summaryOf();
  assert.equal(summary.incidents.filter((i) => i.e === null).length, 4);
  assert.equal(summary.incidents.filter((i) => i.g === 1 && i.e === T + 1200).length, 4);
});

test("a day's first tick keeps 90 days", async () => {
  const day = Math.floor(T / DAY) * DAY + 2 * DAY;
  const old = day - 90 * DAY;
  await store.sql(
    "INSERT INTO samples (t, site, closings, chances, accounts, site_code, closings_code, chances_code, accounts_code, closings_allow, chances_allow) VALUES (?1,'ok','ok','ok','ok',200,200,200,200,0,0), (?2,'ok','ok','ok','ok',200,200,200,200,0,0)",
    old - 300,
    old,
  );
  await store.sql(
    "INSERT INTO days (day, part, ok, late, down) VALUES (?1,'site',9,0,0), (?2,'site',8,0,0)",
    dayOf(old - 1),
    dayOf(old),
  );
  await store.sql(
    "INSERT INTO incidents (part, kind, start, last, ended, gap) VALUES ('site','late',?1,?1,?2,0), ('site','late',?1,?1,?3,0)",
    old - 900,
    old - 300,
    old,
  );
  // The last tick of the day before deletes nothing.
  assert.equal(await tick({ ...WHERE, DB: store.db }, day - 300, net(day - 300)), 'taken');
  assert.deepEqual(await store.sql('SELECT COUNT(*) AS n FROM samples WHERE t < ?', old), [
    { n: 1 },
  ]);
  assert.equal(await tick({ ...WHERE, DB: store.db }, day, net(day)), 'taken');
  assert.deepEqual(await store.sql('SELECT t FROM samples WHERE t <= ?', old), [{ t: old }]);
  assert.deepEqual(await store.sql('SELECT day FROM days WHERE day <= ?', dayOf(old)), [
    { day: dayOf(old) },
  ]);
  assert.deepEqual(await store.sql('SELECT ended FROM incidents WHERE ended <= ?', old), [
    { ended: old },
  ]);
});

test('a tick that cannot write leaves the store as it was', async () => {
  const t = Math.floor(T / DAY) * DAY + 2 * DAY + 300;
  const broken = {
    prepare: (query: string) => store.db.prepare(query),
    batch: (list: D1PreparedStatement[]) =>
      list.length === 2
        ? store.db.batch(list)
        : store.db.batch([...list, store.db.prepare('INSERT INTO nowhere VALUES (1)')]),
  } as unknown as D1Database;
  await assert.rejects(tick({ ...WHERE, DB: broken }, t, net(t)));
  assert.deepEqual(await store.sql('SELECT COUNT(*) AS n FROM samples WHERE t = ?', t), [{ n: 0 }]);
  assert.deepEqual(await store.sql("SELECT v FROM meta WHERE k = 'processed'"), [
    { v: String(t - 300) },
  ]);
});
