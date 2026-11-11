/** One tick: probe the four parts, then write what was found in one transaction. */

import { INCIDENTS_MAX, dayOf, step, windowStart } from '../../shared/history.ts';
import { DAY, DAYS_KEPT, PARTS } from '../../shared/types.ts';
import type { DayRow, Incident, Part, Reading, Sample } from '../../shared/types.ts';
import { probe } from './probe.ts';
import type { Deps, Where } from './probe.ts';

export interface Env extends Where {
  DB: D1Database;
}

const INCIDENT_COLUMNS = 'id, part, kind, start, last, ended, gap';
/**
 * The closed problems a tick reads: the newest by start. The summary lists `INCIDENTS_MAX` in
 * all, newest first with the parts in their order among those that began at one tick, so the
 * newest `INCIDENTS_MAX` and the rest of the last tick among them (a part begins one problem at
 * a tick at most) always hold every one it lists. A part that goes wrong and right for weeks
 * then costs each tick these rows and no more. Both reads walk an index of the migration.
 */
export const CLOSED_READ = INCIDENTS_MAX + PARTS.length - 1;
export const OPEN_SQL = `SELECT ${INCIDENT_COLUMNS} FROM incidents WHERE ended IS NULL`;
export const CLOSED_SQL =
  `SELECT ${INCIDENT_COLUMNS} FROM incidents WHERE ended >= ? ` + 'ORDER BY start DESC LIMIT ?';

/** The stored values a tick starts from, as text: `processed` is the compare-and-set's key. */
interface Kept {
  first: string | null;
  processed: string | null;
}

async function readKept(db: D1Database): Promise<Kept> {
  const meta = await db
    .prepare("SELECT k, v FROM meta WHERE k IN ('first', 'processed')")
    .all<{ k: string; v: string }>();
  const kept = new Map(meta.results.map((row) => [row.k, row.v]));
  return { first: kept.get('first') ?? null, processed: kept.get('processed') ?? null };
}

const taken = (kept: Kept, t: number): boolean =>
  kept.processed !== null && Number(kept.processed) >= t;

/**
 * The first write of a tick's batch, its compare-and-set: it moves `processed` to the tick only
 * while `processed` is still what the tick read. Otherwise the value is NULL, which the column
 * refuses, and the whole batch is rolled back: a tick that overlapped another never writes a
 * summary made from a store it did not read, and an older tick never follows a newer one.
 */
export const MOVE_SQL =
  "INSERT INTO meta (k, v) VALUES ('processed', " +
  "CASE WHEN (SELECT v FROM meta WHERE k = 'processed') IS ? THEN ? END) " +
  'ON CONFLICT (k) DO UPDATE SET v = excluded.v';

/**
 * How many times a tick makes its writes: once, and once more after losing the compare-and-set.
 * One try is at most 24 statements and each read of the stored values one more, so a run stays
 * at 50 or fewer, the free plan's queries for one run. A tick that loses twice throws and shows
 * as a tick with no readings.
 */
export const TRIES = 2;

/**
 * Take the tick `t` (Unix seconds, a multiple of 300) in. A tick is taken in once: a second call
 * for the same or an older tick probes nothing and writes nothing, and so does one that finds,
 * when it comes to write, that a tick as new or newer was written while it probed.
 */
export async function tick(env: Env, t: number, deps: Deps): Promise<'taken' | 'skipped'> {
  const db = env.DB;
  let kept = await readKept(db);
  if (taken(kept, t)) return 'skipped';

  const readings = await Promise.all(PARTS.map((part) => probe(part, env, deps)));
  const parts = {} as Record<Part, Reading>;
  PARTS.forEach((part, i) => {
    parts[part] = readings[i]!;
  });
  const sample: Sample = { t, parts };

  for (let tries = 1; ; tries += 1) {
    const writes = await writesFor(db, sample, kept);
    try {
      // One batch is one transaction: a tick is written whole or not at all.
      await db.batch(writes);
      return 'taken';
    } catch (error) {
      // Lost the compare-and-set only if another tick moved `processed` meanwhile.
      const now = await readKept(db);
      if (now.processed === kept.processed || tries >= TRIES) throw error;
      if (taken(now, t)) return 'skipped';
      kept = now;
    }
  }
}

/** The reads of the store and the batch that takes `sample` in on top of what was `kept`. */
async function writesFor(
  db: D1Database,
  sample: Sample,
  kept: Kept,
): Promise<D1PreparedStatement[]> {
  const { t, parts } = sample;
  const processed = kept.processed === null ? null : Number(kept.processed);
  const start = windowStart(t);
  const [days, open, closed] = await db.batch<Record<string, unknown>>([
    db.prepare('SELECT day, part, ok, late, down FROM days WHERE day >= ?').bind(dayOf(start)),
    db.prepare(OPEN_SQL),
    db.prepare(CLOSED_SQL).bind(start, CLOSED_READ),
  ]);
  const incidents = [...(open?.results ?? []), ...(closed?.results ?? [])];
  const stepped = step(
    {
      first: kept.first === null ? null : Number(kept.first),
      days: (days?.results ?? []) as unknown as DayRow[],
      incidents: incidents as unknown as Incident[],
    },
    sample,
  );

  const { site, closings, chances, accounts } = parts;
  const writes: D1PreparedStatement[] = [
    db.prepare(MOVE_SQL).bind(kept.processed, String(t)),
    db
      .prepare(
        'INSERT INTO samples (t, site, closings, chances, accounts, site_code, closings_code, ' +
          'chances_code, accounts_code, site_ms, accounts_ms, closings_made, chances_made, ' +
          'closings_allow, chances_allow, closings_bytes) ' +
          'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
      )
      .bind(
        t,
        site.s,
        closings.s,
        chances.s,
        accounts.s,
        site.code,
        closings.code,
        chances.code,
        accounts.code,
        site.ms,
        accounts.ms,
        closings.made,
        chances.made,
        closings.allow,
        chances.allow,
        closings.bytes,
      ),
  ];
  for (const row of stepped.add) {
    writes.push(
      db
        .prepare(
          'INSERT INTO days (day, part, ok, late, down) VALUES (?, ?, ?, ?, ?) ' +
            'ON CONFLICT (day, part) DO UPDATE SET ok = ok + excluded.ok, ' +
            'late = late + excluded.late, down = down + excluded.down',
        )
        .bind(row.day, row.part, row.ok, row.late, row.down),
    );
  }
  for (const row of stepped.changed) {
    writes.push(
      db
        .prepare('UPDATE incidents SET kind = ?, last = ?, ended = ?, gap = ? WHERE id = ?')
        .bind(row.kind, row.last, row.ended, row.gap, row.id),
    );
  }
  for (const row of stepped.opened) {
    writes.push(
      db
        .prepare(
          'INSERT INTO incidents (part, kind, start, last, ended, gap) VALUES (?, ?, ?, ?, ?, ?)',
        )
        .bind(row.part, row.kind, row.start, row.last, row.ended, row.gap),
    );
  }
  const put = 'INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT (k) DO UPDATE SET v = excluded.v';
  if (kept.first === null) {
    writes.push(
      db.prepare('INSERT OR IGNORE INTO meta (k, v) VALUES (?, ?)').bind('first', String(t)),
    );
  }
  writes.push(db.prepare(put).bind('summary', JSON.stringify(stepped.summary)));
  // The first tick of a UTC day drops what is older than 90 days.
  if (processed === null || dayOf(processed) !== dayOf(t)) {
    const today = Math.floor(t / DAY) * DAY;
    const before = today - DAYS_KEPT * DAY;
    writes.push(
      db.prepare('DELETE FROM samples WHERE t < ?').bind(before),
      db.prepare('DELETE FROM days WHERE day < ?').bind(dayOf(before)),
      db.prepare('DELETE FROM incidents WHERE ended < ?').bind(before),
    );
  }
  return writes;
}
