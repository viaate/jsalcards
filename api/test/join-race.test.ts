/**
 * Join numbers under load: sign-ups, logins and username picks all at once,
 * round after round, with the counter low, just below #9999 and at #9999, and
 * with accounts that held the counter last in an earlier round asked for a
 * number again. Every number is given at most once, each account gets one
 * number however many of its requests race, no request fails, the counter
 * moves by exactly the numbers given, and nothing goes past #9999.
 *
 * JOIN_RACE_ROUNDS sets the number of rounds (default 12, a few seconds) for a
 * longer run by hand.
 */

import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { after, before, describe, it } from 'node:test';

import { fakeKey, startApi, type Api } from './harness.ts';

let api: Api;
before(async () => {
  api = await startApi();
});
after(async () => {
  await api.close();
});

const LAST_JOIN = 9999;
const ROUNDS = Number(process.env.JOIN_RACE_ROUNDS ?? 12);
/** New sign-ups per round. */
const SIGNUPS = 4;
/** Accounts the old Worker made (numbered 0), asked again every round: two logins each, and a pick for half. */
const POOL = 6;
/** Where the counter starts in a round: low, just below the last number, or at it. */
const BASES = [200, LAST_JOIN - 3, LAST_JOIN, 500, LAST_JOIN - 1, LAST_JOIN];

let counter = 0;
/** Every request from its own network, so the rate limits stay out of the way. */
const ip = () => {
  const n = ++counter;
  return `10.${(n >> 16) & 255}.${(n >> 8) & 255}.${n & 255}`;
};
/** a, b, c...: names and emails stay the same each round, and no digits make a number code. */
const letter = (i: number) => String.fromCharCode(97 + i);
const legacy = (email: string) =>
  createHash('sha256').update(`snowlight-v1|${email}`).digest('base64url');

type Reply = Awaited<ReturnType<Api['call']>>;

function signup(username: string): Promise<Reply> {
  const email = `${username}@example.com`;
  const nameSalt = Buffer.alloc(16, ++counter % 256).toString('base64url');
  return api.call('POST', '/v1/signup', {
    ip: ip(),
    body: {
      name: 'Sam',
      email,
      username,
      over13: true,
      key: fakeKey(`pw|${legacy(email)}`),
      email_salt: legacy(email),
      name_key: fakeKey(`pw|${nameSalt}`),
      name_salt: nameSalt,
    },
  });
}

/** A login by email: the email's v1 salt is its client salt. */
function login(email: string): Promise<Reply> {
  return api.call('POST', '/v1/login', {
    ip: ip(),
    body: { login: email, key: fakeKey(`pw|${legacy(email)}`) },
  });
}

describe('join numbers under concurrent sign-ups, logins and picks', () => {
  it(`give every number once and every account one, in ${ROUNDS} rounds`, async () => {
    const pool: { id: string; email: string; token: string }[] = [];
    for (let k = 0; k < POOL; k++) {
      const r = await signup(`pool_${letter(k)}`);
      assert.equal(r.status, 201);
      pool.push({
        id: r.body.user.id,
        email: `pool_${letter(k)}@example.com`,
        token: r.body.token,
      });
    }
    const ids = JSON.stringify(pool.map((p) => p.id));
    let requests = 0;
    for (let round = 0; round < ROUNDS; round++) {
      const base = BASES[round % BASES.length]!;
      // Half the pool has no username, so its pick races its own logins.
      const pickers = new Set(pool.filter((_, k) => (k + round) % 2 === 0).map((p) => p.id));
      // Test only: the last round's sign-ups and the pool's numbers freed, the
      // limits cleared, and the counter set. The holder is left as it was, so a
      // pool account that took the last number in the round before is asked again.
      await api.sql("DELETE FROM users WHERE username GLOB 'rx_*'");
      await api.sql('DELETE FROM rate_limits');
      await api.sql(
        `UPDATE users SET join_number = NULL, numbered = 0,
           username = CASE WHEN id IN (SELECT value FROM json_each(?2)) THEN NULL
                           ELSE substr(login, 1, instr(login, '@') - 1) END
         WHERE id IN (SELECT value FROM json_each(?1))`,
        ids,
        JSON.stringify([...pickers]),
      );
      await api.sql("UPDATE counters SET value = ?1 WHERE name = 'join'", base);

      const asks = [
        ...Array.from({ length: SIGNUPS }, (_, i) =>
          signup(`rx_${letter(i)}`).then((r) => ({ id: '', r })),
        ),
        ...pool.flatMap((p, k) => [
          login(p.email).then((r) => ({ id: p.id, r })),
          login(p.email).then((r) => ({ id: p.id, r })),
          ...(pickers.has(p.id)
            ? [
                api
                  .call('PUT', '/v1/me/username', {
                    token: p.token,
                    body: { username: `pick_${letter(k)}` },
                  })
                  .then((r) => ({ id: p.id, r })),
              ]
            : []),
        ]),
      ];
      const replies = await Promise.all(asks);
      requests += replies.length;

      for (const { r } of replies)
        assert.ok(
          r.status === 200 || r.status === 201,
          `round ${round}: ${r.status} ${JSON.stringify(r.body)}`,
        );
      const rows = new Map<string, { join_number: number | null; numbered: number }>(
        (
          await api.sql(
            'SELECT id, join_number, numbered FROM users WHERE id IN (SELECT value FROM json_each(?1))',
            ids,
          )
        ).map((row) => [row.id, row]),
      );
      const given: number[] = [];
      for (const { id, r } of replies)
        if (id === '' && r.body.user.join_number !== null) given.push(r.body.user.join_number);
      // Each pool account: one number (or none), the same in every reply, and the one it holds.
      for (const p of pool) {
        const told = new Set(
          replies.filter((x) => x.id === p.id).map((x) => x.r.body.user.join_number),
        );
        const row = rows.get(p.id)!;
        assert.deepEqual([...told], [row.join_number], `round ${round}: ${p.email}`);
        assert.equal(row.numbered, 1);
        if (row.join_number !== null) given.push(row.join_number);
      }
      // The numbers after the base, each once, as many as were left, and the
      // counter moved by exactly that many.
      const granted = Math.min(SIGNUPS + POOL, LAST_JOIN - base);
      assert.deepEqual(
        given.sort((a, b) => a - b),
        Array.from({ length: granted }, (_, i) => base + 1 + i),
        `round ${round} from ${base}`,
      );
      const [{ value, holder }] = await api.sql(
        "SELECT value, holder FROM counters WHERE name = 'join'",
      );
      assert.equal(value, base + granted);
      assert.ok(value <= LAST_JOIN);
      // No transaction leaves its holder behind.
      assert.equal(holder, null);
    }
    assert.equal(requests, ROUNDS * (SIGNUPS + POOL * 2 + POOL / 2));
  });
});
