/**
 * Usernames: the login salt, the live availability check, picking one, and the
 * admin's moderation terms, scans and renames.
 *
 * CPU budget (10 ms per request on the free plan): the file's lists compile
 * at the Worker's startup (index.ts) and the admin's terms once per isolate
 * for each set (usernames/check.ts), so a check is tens to a few hundred
 * microseconds; a scan reads one page of usernames per request (at most
 * SCAN_PAGE, ended early by the work it holds: scanPage, sized from a
 * measured fresh-isolate first page of the slowest names with MAX_ADMIN_TERMS
 * of every kind) so it stays under 5 ms however many accounts there are, and
 * the admin view asks for the next page until it is done.
 */

import { adminLogin, audit, giveJoinNumber } from './account';
import { bucket, hit, hits, publicUser, requireAdmin, requireSession, type UserRow } from './auth';
import { HttpError, clientIp, json, readBody, type Env } from './http';
import {
  MAX_ADMIN_TERMS,
  MAX_USERNAME,
  SCAN_PAGE,
  checkUsername,
  scanPage,
  canonicalUsername,
  rawOf,
  termOf,
  renameTerm,
  termScanner,
  usernameSkeletons,
  BLOCKLIST_VERSION,
  type ExtraTerms,
} from './usernames/check';
import { b64url, sha256 } from './util';

export { SCAN_PAGE };
const KINDS = ['substring', 'token', 'allow', 'raw'] as const;
type Kind = (typeof KINDS)[number];

/** Per-address limits on the two lookups anyone can make: login salts and the live username check. */
const LOOKUP_WINDOW = 15 * 60 * 1000;
export const SALT_LIMIT = 30;
export const CHECK_LIMIT = 120;

async function limitLookups(
  env: Env,
  request: Request,
  kind: string,
  limit: number,
  now: number,
): Promise<void> {
  const [count] = await hits(env, [
    hit(env, await bucket(kind, clientIp(request)), LOOKUP_WINDOW, now),
  ]);
  if (count! > limit) throw new HttpError(429, 'too_many');
}

export async function extraTerms(env: Env): Promise<ExtraTerms> {
  const { results } = await env.DB.prepare('SELECT term, kind FROM moderation_terms').all<{
    term: string;
    kind: Kind;
  }>();
  const of = (kind: Kind) => results.filter((r) => r.kind === kind).map((r) => r.term);
  return { substring: of('substring'), token: of('token'), allow: of('allow'), raw: of('raw') };
}

/** How long a deleted account's username is held, so that nobody can take it at once and pass for that person. */
export const RELEASED_HOLD = 30 * 24 * 60 * 60 * 1000;

/** The key a held skeleton is kept under: its hash, never the name. */
async function heldKey(skeleton: string): Promise<string> {
  return b64url(await sha256(`snowlight-held|${skeleton}`));
}

/**
 * Holds a username and its look-alikes for good (until null: a name an admin
 * rename took away) or until a time (a deleted account's). A name taken away
 * is held by its leet skeleton and its letters alone, so that the same
 * letters with any digits or underscores added, dropped or moved
 * (meanname1, mean_name_99, 7meanname) stay held; a deleted account's only by
 * its leet skeleton (Mean_Name, m3anname), so that a name with a year in it
 * does not hold the plain name. A hold for good stays for good.
 */
export async function holdUsername(
  env: Env,
  name: string,
  until: number | null,
): Promise<D1PreparedStatement[]> {
  const skeletons = usernameSkeletons(name);
  const held = until === null ? skeletons.slice(0, 2) : skeletons.slice(0, 1);
  return Promise.all(
    held.map(async (skeleton) =>
      env.DB.prepare(
        `INSERT INTO held_usernames (skeleton_hash, until) VALUES (?1, ?2)
         ON CONFLICT (skeleton_hash) DO UPDATE SET until = CASE
           WHEN held_usernames.until IS NULL OR excluded.until IS NULL THEN NULL
           ELSE MAX(held_usernames.until, excluded.until) END`,
      ).bind(await heldKey(skeleton), until),
    ),
  );
}

/**
 * A username anyone may take, canonical (lowercase), or an HttpError: the
 * format, reserved and blocklist rules (with the admin's terms), then whether
 * another account has it, or it (in any spelling) is held: taken away by an
 * admin rename, or a deleted account's for 30 days. A held name reads as
 * taken.
 */
export async function usableUsername(
  env: Env,
  value: unknown,
  self: string | null,
  now: number,
): Promise<string> {
  if (typeof value !== 'string') throw new HttpError(400, 'username_length');
  const verdict = checkUsername(value, {
    adminName: adminLogin(env),
    extra: await extraTerms(env),
  });
  if (verdict !== null) throw new HttpError(400, verdict.problem);
  const name = canonicalUsername(value);
  const taken = await env.DB.prepare('SELECT id FROM users WHERE username = ?1')
    .bind(name)
    .first<{ id: string }>();
  if (taken !== null) {
    if (taken.id !== self) throw new HttpError(409, 'username_taken');
    return name;
  }
  // Every skeleton of the name, so that a held name with digits added,
  // dropped or read as letters is found (usernameSkeletons).
  const keys = await Promise.all(usernameSkeletons(name).map(heldKey));
  const { results: held } = await env.DB.prepare(
    `SELECT until FROM held_usernames WHERE skeleton_hash IN (${keys.map((_, i) => `?${i + 1}`).join(', ')})`,
  )
    .bind(...keys)
    .all<{ until: number | null }>();
  if (held.some((row) => row.until === null || row.until > now))
    throw new HttpError(409, 'username_taken');
  return name;
}

/**
 * SHA-256("snowlight-v1|" + login): the client salt of every email key (the
 * browser can make it itself, so asking for it tells nothing) and of the
 * admin's key.
 */
export async function legacySalt(login: string): Promise<string> {
  return b64url(await sha256(`snowlight-v1|${login}`));
}

/**
 * POST /v1/login/salt {login}: the salt to derive a login's key with. An
 * email's is always legacySalt(email), looked up nowhere, so the answer is
 * the same whether the email has an account or not. A username's is the
 * random salt its account made; an unknown username (or one with no username
 * key yet) gets a made-up salt that stays the same for it, from a secret kept
 * in D1, so the answer does not say whether it exists. An email and a username
 * of one account have unrelated salts. Limited per address.
 */
export async function loginSalt(env: Env, request: Request, now: number): Promise<Response> {
  const body = await readBody(request);
  const login = typeof body.login === 'string' ? body.login.trim().toLowerCase() : '';
  if (login.length === 0 || login.length > 254) throw new HttpError(400, 'bad_login');
  await limitLookups(env, request, 'salt-ip', SALT_LIMIT, now);
  if (login === adminLogin(env) || login.includes('@'))
    return json(200, { salt: await legacySalt(login) });
  const row = await env.DB.prepare(
    "SELECT name_salt FROM users WHERE username = ?1 AND role = 'user'",
  )
    .bind(login)
    .first<Pick<UserRow, 'name_salt'>>();
  if (row !== null && row.name_salt !== null) return json(200, { salt: row.name_salt });
  return json(200, { salt: await madeUpSalt(env, login) });
}

/** The made-up salts' secret: made at random by the migration, kept in D1, read once per isolate. */
let saltSecret: { db: D1Database; key: CryptoKey } | null = null;

async function madeUpSalt(env: Env, login: string): Promise<string> {
  if (saltSecret === null || saltSecret.db !== env.DB) {
    const row = await env.DB.prepare(
      "SELECT value FROM settings WHERE name = 'salt_secret'",
    ).first<{
      value: string;
    }>();
    if (row === null) throw new HttpError(500, 'server');
    const key = await crypto.subtle.importKey(
      'raw',
      new TextEncoder().encode(row.value),
      { name: 'HMAC', hash: 'SHA-256' },
      false,
      ['sign'],
    );
    saltSecret = { db: env.DB, key };
  }
  const mac = await crypto.subtle.sign('HMAC', saltSecret.key, new TextEncoder().encode(login));
  return b64url(new Uint8Array(mac).subarray(0, 16));
}

/** GET /v1/usernames/check?name=: whether a username may be taken now. Limited per address. */
export async function checkName(env: Env, request: Request, now: number): Promise<Response> {
  await limitLookups(env, request, 'check-ip', CHECK_LIMIT, now);
  const name = new URL(request.url).searchParams.get('name') ?? '';
  try {
    const username = await usableUsername(env, name.slice(0, 40), null, now);
    return json(200, { ok: true, username });
  } catch (error) {
    if (error instanceof HttpError) return json(200, { ok: false, problem: error.code });
    throw error;
  }
}

/**
 * PUT /v1/me/username {username}: an account with no username, or one the admin
 * changed, picks its own. It needs a username key first (needs_rekey false).
 */
export async function putUsername(env: Env, request: Request, now: number): Promise<Response> {
  const { user } = await requireSession(env, request, now);
  if (user.role === 'admin') throw new HttpError(400, 'admin_managed');
  if (user.username !== null && user.rename_required === 0)
    throw new HttpError(409, 'username_set');
  if (user.name_salt === null || user.email_salt === null) throw new HttpError(409, 'needs_rekey');
  const body = await readBody(request);
  const username = await usableUsername(env, body.username, user.id, now);
  try {
    await env.DB.prepare('UPDATE users SET username = ?2, rename_required = 0 WHERE id = ?1')
      .bind(user.id, username)
      .run();
  } catch {
    // Two accounts picked it at once: the unique index let one through.
    throw new HttpError(409, 'username_taken');
  }
  const join_number = await giveJoinNumber(env, user);
  return json(200, { user: publicUser({ ...user, username, rename_required: 0, join_number }) });
}

// ---- Admin ----

/** GET /v1/admin/moderation: the admin's terms and the file list's version. */
export async function moderation(env: Env, request: Request, now: number): Promise<Response> {
  await requireAdmin(env, request, now);
  const { results } = await env.DB.prepare(
    'SELECT term, kind, added_at FROM moderation_terms ORDER BY kind, term',
  ).all<{ term: string; kind: Kind; added_at: number }>();
  return json(200, {
    version: BLOCKLIST_VERSION,
    terms: results.map((r) => ({
      term: r.term,
      kind: r.kind,
      added_at: new Date(r.added_at).toISOString(),
    })),
  });
}

function kindOf(value: unknown): Kind {
  if (typeof value === 'string' && (KINDS as readonly string[]).includes(value))
    return value as Kind;
  throw new HttpError(400, 'bad_kind');
}

/** A term as stored: letters only (leet read as letters), or for a number code, letters and digits. */
function termFrom(value: unknown, kind: Kind): string {
  const text = typeof value === 'string' && value.length <= 40 ? value : '';
  const term = kind === 'raw' ? rawOf(text) : termOf(text);
  // A name has at most 20 letters, so a longer term could never match one.
  if (term.length < 2 || term.length > MAX_USERNAME) throw new HttpError(400, 'bad_term');
  return term;
}

/** POST /v1/admin/moderation/terms {term, kind}: takes effect at once for every check. */
export async function addTerm(env: Env, request: Request, now: number): Promise<Response> {
  const { user: admin } = await requireAdmin(env, request, now);
  const body = await readBody(request);
  const kind = kindOf(body.kind);
  const term = termFrom(body.term, kind);
  const count = await env.DB.prepare('SELECT COUNT(*) AS n FROM moderation_terms WHERE kind = ?1')
    .bind(kind)
    .first<{ n: number }>();
  if ((count?.n ?? 0) >= MAX_ADMIN_TERMS) throw new HttpError(400, 'too_many_terms');
  await env.DB.prepare(
    'INSERT INTO moderation_terms (term, kind, added_at) VALUES (?1, ?2, ?3) ON CONFLICT DO NOTHING',
  )
    .bind(term, kind, now)
    .run();
  await audit(env, now, admin, 'add_term', null, { term, kind });
  return json(200, { term, kind });
}

/** DELETE /v1/admin/moderation/terms/<kind>:<term> */
export async function removeTerm(
  env: Env,
  request: Request,
  now: number,
  key: string,
): Promise<Response> {
  const { user: admin } = await requireAdmin(env, request, now);
  const [rawKind = '', rawTerm = ''] = key.split(':');
  const kind = kindOf(rawKind);
  const term = termFrom(rawTerm, kind);
  const result = await env.DB.prepare('DELETE FROM moderation_terms WHERE term = ?1 AND kind = ?2')
    .bind(term, kind)
    .run();
  if ((result.meta.changes ?? 0) === 0) throw new HttpError(404, 'not_found');
  await audit(env, now, admin, 'remove_term', null, { term, kind });
  return json(200, { ok: true });
}

interface ScanRow {
  id: string;
  username: string;
  join_number: number | null;
}

/**
 * GET /v1/admin/moderation/scan?after=<username>[&term=&kind=]: one page of
 * usernames in order, and those on it that one term catches (a term just
 * added) or, with no term, that the whole list catches now (file list plus the
 * admin's terms). Accounts the admin renamed are left out until they pick a
 * name of their own (their player_ name is refused by design, and their pick
 * is checked then). `next` is the cursor for the following page, null at the
 * end.
 */
export async function scanNames(env: Env, request: Request, now: number): Promise<Response> {
  await requireAdmin(env, request, now);
  const url = new URL(request.url);
  const after = (url.searchParams.get('after') ?? '').slice(0, 40);
  const rawTerm = url.searchParams.get('term');
  const extra = await extraTerms(env);
  let test: (name: string) => string | null;
  // The admin's terms this request may compile (its work counts against the page).
  let compiles: ExtraTerms = extra;
  if (rawTerm !== null) {
    const kind = kindOf(url.searchParams.get('kind'));
    if (kind === 'allow') throw new HttpError(400, 'bad_kind');
    const term = termFrom(rawTerm, kind);
    compiles = { allow: extra.allow ?? [] };
    const scanner = termScanner(term, kind, compiles.allow);
    test = (name) => (scanner(name) ? term : null);
  } else {
    const adminName = adminLogin(env);
    test = (name) => {
      const verdict = checkUsername(name, { adminName, extra });
      return verdict === null ? null : (verdict.term ?? verdict.problem);
    };
  }
  const { results } = await env.DB.prepare(
    "SELECT id, username, join_number FROM users WHERE role = 'user' AND username IS NOT NULL AND rename_required = 0 AND username > ?1 ORDER BY username LIMIT ?2",
  )
    .bind(after, SCAN_PAGE)
    .all<ScanRow>();
  // A page ends early by the work it holds (the slowest names, or the
  // admin's terms compiled first in this isolate), so it stays well under the
  // CPU limit; the admin view asks for the next one.
  const count =
    results.length === 0
      ? 0
      : scanPage(
          results.map((r) => r.username),
          compiles,
        );
  const matches = [];
  for (const row of results.slice(0, count)) {
    const hit = test(row.username);
    if (hit !== null)
      matches.push({ id: row.id, username: row.username, join_number: row.join_number, term: hit });
  }
  const more = count < results.length || results.length === SCAN_PAGE;
  return json(200, {
    matches,
    scanned: count,
    next: more ? results[count - 1]!.username : null,
  });
}

/**
 * POST /v1/admin/users/:id/rename {username?, block?}: gives the account the
 * name the admin typed (it must pass the same rules) or player_<join number>,
 * and makes its next sign-in ask it to pick a new one. With block (the
 * default; the admin view's "Also block this word for everyone"), the letters
 * of the name it picked itself become one of the admin's blocked words
 * (renameTerm), so that the name with any affix, digits or spelling trick is
 * refused to everyone; `blocked` says which word, or `block_problem` why none
 * was added (too short, or 50 words of that kind already).
 */
export async function renameUser(
  env: Env,
  request: Request,
  now: number,
  id: string,
): Promise<Response> {
  const { user: admin } = await requireAdmin(env, request, now);
  const body = await readBody(request);
  if (!/^[0-9a-f]{32}$/.test(id)) throw new HttpError(404, 'not_found');
  const target = await env.DB.prepare('SELECT * FROM users WHERE id = ?1')
    .bind(id)
    .first<UserRow>();
  if (target === null) throw new HttpError(404, 'not_found');
  if (target.role === 'admin') throw new HttpError(400, 'admin_managed');
  let username: string;
  if (body.username === undefined || body.username === null || body.username === '') {
    username =
      target.join_number !== null
        ? `player_${String(target.join_number).padStart(4, '0')}`
        : `player_${parseInt(target.id.slice(0, 8), 16) % 100_000_000}`;
    const taken = await env.DB.prepare('SELECT id FROM users WHERE username = ?1 AND id != ?2')
      .bind(username, id)
      .first();
    if (taken !== null)
      username = `player_${parseInt(target.id.slice(0, 12), 16) % 1_000_000_000_000}`;
  } else {
    username = await usableUsername(env, body.username, id, now);
  }
  // The name the account picked itself is held for good, in every spelling, so
  // that its next pick (or anyone else's) cannot be the same name again. A
  // name an admin gave it is not.
  const statements = [
    env.DB.prepare('UPDATE users SET username = ?2, rename_required = 1 WHERE id = ?1').bind(
      id,
      username,
    ),
  ];
  const ownPick = target.username !== null && target.rename_required === 0;
  if (ownPick && target.username !== username)
    statements.push(...(await holdUsername(env, target.username!, null)));
  let blocked: { term: string; kind: Kind } | null = null;
  let blockProblem: 'too_short' | 'too_many_terms' | null = null;
  if (ownPick && body.block !== false) {
    blocked = renameTerm(target.username!);
    if (blocked === null) blockProblem = 'too_short';
    else {
      const { term, kind } = blocked;
      const room = await env.DB.prepare(
        `SELECT (SELECT COUNT(*) FROM moderation_terms WHERE kind = ?2) AS n,
                EXISTS (SELECT 1 FROM moderation_terms WHERE term = ?1 AND kind = ?2) AS known`,
      )
        .bind(term, kind)
        .first<{ n: number; known: number }>();
      if (room !== null && room.known === 0 && room.n >= MAX_ADMIN_TERMS) {
        blocked = null;
        blockProblem = 'too_many_terms';
      } else
        statements.push(
          env.DB.prepare(
            'INSERT INTO moderation_terms (term, kind, added_at) VALUES (?1, ?2, ?3) ON CONFLICT DO NOTHING',
          ).bind(term, kind, now),
        );
    }
  }
  try {
    await env.DB.batch(statements);
  } catch {
    throw new HttpError(409, 'username_taken');
  }
  await audit(env, now, admin, 'rename_user', id, {
    from: target.username,
    to: username,
    join_number: target.join_number,
  });
  if (blocked !== null) await audit(env, now, admin, 'add_term', null, blocked);
  return json(200, { id, username, blocked, block_problem: blockProblem });
}
