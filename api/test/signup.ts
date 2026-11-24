/** A new account on `target`, for tests that need one signed in. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { fakeKey, type Api } from './harness.ts';

export async function signupOn(
  target: Api,
  prefix: string,
  n: number,
): Promise<{ token: string; id: string; email: string }> {
  const email = `${prefix}${n}@example.com`;
  const r = await target.call('POST', '/v1/signup', {
    body: {
      name: 'Pat Lee',
      email,
      key: fakeKey(email),
      email_salt: createHash('sha256').update(`snowlight-v1|${email}`).digest('base64url'),
      name_key: fakeKey(`name|${email}`),
      name_salt: Buffer.alloc(16, n).toString('base64url'),
      username: `${prefix}_${letters(n)}`,
      over13: true,
    },
    ip: `198.20.${n % 250}.${(n % 200) + 1}`,
  });
  assert.equal(r.status, 201, JSON.stringify(r.body));
  return { token: r.body.token, id: r.body.user.id, email };
}

/** n in letters ("b", "ba"...): usernames that differ by more than their digits. */
function letters(n: number): string {
  let out = '';
  let rest = n;
  do {
    out = String.fromCharCode(97 + (rest % 26)) + out;
    rest = Math.floor(rest / 26);
  } while (rest > 0);
  return out.padStart(3, 'q');
}
