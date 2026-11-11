import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { CLOSED_READ, CLOSED_SQL, MOVE_SQL, OPEN_SQL, tick } from '../prober/src/tick.ts';
import type { Deps } from '../prober/src/probe.ts';
import { INCIDENTS_MAX, dayOf, summarize, windowStart } from '../shared/history.ts';
import { DAY, PARTS, TICK } from '../shared/types.ts';
import type { Incident, Sample, Summary } from '../shared/types.ts';
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
  // The stored values, three reads, the sample, 4 days, 4 problems closed where the readings
  // stopped, 4 opened, the tick, the summary and the day's 3 deletes.
  assert.equal(watch.statements(), 22);
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
      list.length === 3
        ? store.db.batch(list)
        : store.db.batch([...list, store.db.prepare('INSERT INTO nowhere VALUES (1)')]),
  } as unknown as D1Database;
  await assert.rejects(tick({ ...WHERE, DB: broken }, t, net(t)));
  assert.deepEqual(await store.sql('SELECT COUNT(*) AS n FROM samples WHERE t = ?', t), [{ n: 0 }]);
  assert.deepEqual(await store.sql("SELECT v FROM meta WHERE k = 'processed'"), [
    { v: String(t - 300) },
  ]);
});

test('a part that went wrong for weeks costs a tick a bounded read, and the summary is the same', async () => {
  const fresh = await startStore();
  try {
    const t = Math.floor(T / DAY) * DAY + 40 * DAY;
    const start = windowStart(t);
    // 600 closed problems, four parts beginning one at every tick, so the newest hundred end in
    // the middle of a tick's four; one long one that began before the window and ended in it;
    // one that ended before the window and waits for the day's delete; and one still open.
    const rows: string[] = [];
    for (let i = 0; i < 150; i += 1) {
      const began = t - 2 * DAY - i * 3 * TICK;
      for (const part of PARTS) rows.push(`('${part}','late',${began},${began},${began + TICK},0)`);
    }
    rows.push(`('site','down',${start - 5 * DAY},${start + DAY},${start + DAY + TICK},0)`);
    rows.push(`('site','down',${start - 3 * DAY},${start - 2 * DAY},${start - TICK},0)`);
    rows.push(`('accounts','down',${t - DAY},${t - TICK},NULL,0)`);
    for (let i = 0; i < rows.length; i += 100) {
      await fresh.sql(
        `INSERT INTO incidents (part, kind, start, last, ended, gap) VALUES ${rows.slice(i, i + 100).join(',')}`,
      );
    }
    const before = await fresh.sql<Incident>('SELECT * FROM incidents');
    assert.equal(before.length, 603);

    // What the reads cost and return, as D1 counts it.
    const reads: { rows: number; read: number }[] = [];
    const watched = {
      prepare: (query: string) => fresh.db.prepare(query),
      async batch(list: D1PreparedStatement[]) {
        const results = await fresh.db.batch(list);
        if (list.length === 3) {
          for (const result of results) {
            reads.push({ rows: result.results.length, read: result.meta.rows_read });
          }
        }
        return results;
      },
    } as unknown as D1Database;
    const web = healthy(new Net(t * 1000 + 2000)).on(WHERE.ACCOUNTS_HEALTH_URL, { status: 500 });
    assert.equal(await tick({ ...WHERE, DB: watched }, t, web), 'taken');
    const [, open, closed] = reads as [unknown, (typeof reads)[0], (typeof reads)[0]];
    assert.equal(CLOSED_READ, INCIDENTS_MAX + 3);
    assert.deepEqual([open.rows, closed.rows], [1, CLOSED_READ]);
    // Neither read walks the table: the open one reads its one row, the closed one a few more
    // than it returns (the one that ended before the window is passed over).
    assert.equal(open.read <= 2, true, `open read ${open.read}`);
    assert.equal(closed.read <= 2 * CLOSED_READ + 2, true, `closed read ${closed.read}`);

    // The summary is the one a read of every row gives.
    const summary = JSON.parse(
      (await fresh.sql<{ v: string }>("SELECT v FROM meta WHERE k = 'summary'"))[0]!.v,
    ) as Summary;
    const after = await fresh.sql<Incident>('SELECT * FROM incidents');
    const sample = { t, parts: {} } as unknown as Sample;
    for (const part of PARTS) {
      (sample.parts as Record<string, unknown>)[part] = { s: summary.parts[part].s, made: null };
    }
    const whole = summarize(sample, summary.first, [], after);
    assert.equal(summary.incidents.length, INCIDENTS_MAX);
    assert.deepEqual(summary.incidents, whole.incidents);
    assert.equal(summary.incidents[0]!.e, null);
    // The hundred end inside one tick's four parts, in the parts' order.
    const last = summary.incidents.slice(-3).map((i) => [i.p, i.s]);
    assert.equal(new Set(last.map(([, s]) => s)).size, 1);
    assert.deepEqual(
      last.map(([p]) => p),
      PARTS.slice(0, 3),
    );

    // And the plans say so: each read names its index.
    for (const [sql, index, params] of [
      [OPEN_SQL, 'incidents_open', []],
      [CLOSED_SQL, 'incidents_start', [start, CLOSED_READ]],
    ] as const) {
      const plan = await fresh.sql<{ detail: string }>(`EXPLAIN QUERY PLAN ${sql}`, ...params);
      const said = plan.map((row) => row.detail).join(' | ');
      assert.match(said, new RegExp(`USING INDEX ${index}`), said);
      assert.equal(/TEMP B-TREE/.test(said), false, said);
    }
  } finally {
    await fresh.close();
  }
});

/** A network that holds every answer until `open()` is called: a tick that probes slowly. */
function held(web: Net): { deps: Deps; open: () => void } {
  let open = (): void => {};
  const gate = new Promise<void>((resolve) => {
    open = resolve;
  });
  const deps: Deps = {
    fetch: async (url, init) => {
      await gate;
      return web.fetch(url, init);
    },
    now: () => web.now(),
    wait: (ms) => web.wait(ms),
  };
  return { deps, open };
}

test('overlapping ticks: an older tick that ends last never overwrites a newer one', async () => {
  const fresh = await startStore();
  try {
    const t0 = Math.floor(T / DAY) * DAY + 50 * DAY;
    const [t1, t2] = [t0 + TICK, t0 + 2 * TICK];
    const env = { ...WHERE, DB: fresh.db };
    assert.equal(await tick(env, t0, net(t0)), 'taken');
    // t1 reads the store and probes slowly; t2 starts, probes and commits while t1 waits.
    const slow = held(healthy(new Net(t1 * 1000 + 2000)).on(WHERE.SITE_URL, { status: 500 }));
    const first = tick(env, t1, slow.deps);
    await new Promise((resolve) => setTimeout(resolve, 50));
    assert.equal(await tick(env, t2, net(t2)), 'taken');
    slow.open();
    // t1 loses the compare-and-set, reads the store again, finds t2 and writes nothing.
    assert.equal(await first, 'skipped');
    const meta = await fresh.sql<{ k: string; v: string }>('SELECT k, v FROM meta ORDER BY k');
    const values = new Map(meta.map((row) => [row.k, row.v]));
    assert.equal(values.get('processed'), String(t2));
    const summary = JSON.parse(values.get('summary')!) as Summary;
    assert.equal(summary.now, t2);
    assert.equal(summary.parts.site.s, 'ok');
    assert.deepEqual(await fresh.sql('SELECT t FROM samples ORDER BY t'), [{ t: t0 }, { t: t2 }]);
    assert.deepEqual(await fresh.sql('SELECT COUNT(*) AS n FROM incidents'), [{ n: 0 }]);
    assert.deepEqual(
      await fresh.sql('SELECT ok, down FROM days WHERE day = ? AND part = ?', dayOf(t2), 'site'),
      [{ ok: 2, down: 0 }],
    );
  } finally {
    await fresh.close();
  }
});

test('overlapping ticks: a newer tick that ends last reads the store again and keeps both', async () => {
  const fresh = await startStore();
  try {
    const t0 = Math.floor(T / DAY) * DAY + 60 * DAY;
    const [t1, t2] = [t0 + TICK, t0 + 2 * TICK];
    const env = { ...WHERE, DB: fresh.db };
    assert.equal(await tick(env, t0, net(t0)), 'taken');
    // t2 reads the store before t1 commits, so the summary it would write lacks t1's sample.
    const slow = held(healthy(new Net(t2 * 1000 + 2000)));
    const second = tick(env, t2, slow.deps);
    await new Promise((resolve) => setTimeout(resolve, 50));
    const bad = healthy(new Net(t1 * 1000 + 2000)).on(WHERE.SITE_URL, { status: 500 });
    assert.equal(await tick(env, t1, bad), 'taken');
    slow.open();
    assert.equal(await second, 'taken');
    const summary = await fresh.sql<{ v: string }>("SELECT v FROM meta WHERE k = 'summary'");
    const parsed = JSON.parse(summary[0]!.v) as Summary;
    assert.equal(parsed.now, t2);
    // t1's problem is in the summary t2 wrote, closed at t2: t2 was made from t1's store.
    assert.deepEqual(
      parsed.incidents.map((i) => [i.p, i.s, i.e]),
      [['site', t1, t2]],
    );
    assert.deepEqual(
      await fresh.sql('SELECT ok, down FROM days WHERE day = ? AND part = ?', dayOf(t2), 'site'),
      [{ ok: 2, down: 1 }],
    );
    assert.deepEqual(await fresh.sql("SELECT v FROM meta WHERE k = 'processed'"), [
      { v: String(t2) },
    ]);
  } finally {
    await fresh.close();
  }
});

test('the compare-and-set refuses a tick whose store moved, and the batch is undone whole', async () => {
  const fresh = await startStore();
  try {
    const t0 = Math.floor(T / DAY) * DAY + 70 * DAY;
    await tick({ ...WHERE, DB: fresh.db }, t0, net(t0));
    const db = fresh.db;
    await assert.rejects(
      db.batch([
        db.prepare("INSERT INTO meta (k, v) VALUES ('probe', '1')"),
        db.prepare(MOVE_SQL).bind(String(t0 - TICK), String(t0 + TICK)),
      ]),
      /NOT NULL/,
    );
    assert.deepEqual(await fresh.sql("SELECT v FROM meta WHERE k IN ('probe', 'processed')"), [
      { v: String(t0) },
    ]);
    await db.batch([db.prepare(MOVE_SQL).bind(String(t0), String(t0 + TICK))]);
    assert.deepEqual(await fresh.sql("SELECT v FROM meta WHERE k = 'processed'"), [
      { v: String(t0 + TICK) },
    ]);
  } finally {
    await fresh.close();
  }
});
