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

/**
 * Take the tick `t` (Unix seconds, a multiple of 300) in. A tick is taken in once: a second call
 * for the same or an older tick probes nothing and writes nothing.
 */
export async function tick(env: Env, t: number, deps: Deps): Promise<'taken' | 'skipped'> {
  const db = env.DB;
  const meta = await db
    .prepare("SELECT k, v FROM meta WHERE k IN ('first', 'processed')")
    .all<{ k: string; v: string }>();
  const kept = new Map(meta.results.map((row) => [row.k, Number(row.v)]));
  const processed = kept.get('processed') ?? null;
  if (processed !== null && processed >= t) return 'skipped';

  const readings = await Promise.all(PARTS.map((part) => probe(part, env, deps)));
  const parts = {} as Record<Part, Reading>;
  PARTS.forEach((part, i) => {
    parts[part] = readings[i]!;
  });
  const sample: Sample = { t, parts };

  const start = windowStart(t);
  const [days, open, closed] = await db.batch<Record<string, unknown>>([
    db.prepare('SELECT day, part, ok, late, down FROM days WHERE day >= ?').bind(dayOf(start)),
    db.prepare(OPEN_SQL),
    db.prepare(CLOSED_SQL).bind(start, CLOSED_READ),
  ]);
  const incidents = [...(open?.results ?? []), ...(closed?.results ?? [])];
  const stepped = step(
    {
      first: kept.get('first') ?? null,
      days: (days?.results ?? []) as unknown as DayRow[],
      incidents: incidents as unknown as Incident[],
    },
    sample,
  );

  const { site, closings, chances, accounts } = parts;
  const writes: D1PreparedStatement[] = [
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
  writes.push(db.prepare(put).bind('processed', String(t)));
  if (!kept.has('first')) {
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
  // One batch is one transaction: a tick is written whole or not at all.
  await db.batch(writes);
  return 'taken';
}
