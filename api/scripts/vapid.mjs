// Makes the VAPID key pair the notification pushes are signed with, once (docs/notify.md).
// api.yml runs it after the migrations. When the database's settings table holds no
// vapid_public and no vapid_private row, it makes a fresh P-256 pair and stores both in one
// INSERT, sent to D1 over the Cloudflare API with the keys as bound parameters, so the
// private key is never in a command line, a SQL text or the log. When either row is there
// it changes nothing: a key pair is made once and kept, so the browsers' subscriptions keep
// working. It prints only "made" or "kept".
//
// Usage: CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=... D1_DATABASE_ID=... node scripts/vapid.mjs

import { generateKeyPairSync } from 'node:crypto';

/**
 * A fresh key pair as the browser and the sender take it: the public key as the
 * uncompressed point (65 bytes, 0x04 first) and the private key as its 32-byte scalar,
 * both base64url.
 */
export function makeKeys() {
  const { privateKey } = generateKeyPairSync('ec', { namedCurve: 'P-256' });
  const jwk = privateKey.export({ format: 'jwk' });
  const point = Buffer.concat([
    Buffer.from([4]),
    Buffer.from(jwk.x, 'base64url'),
    Buffer.from(jwk.y, 'base64url'),
  ]);
  return { publicKey: point.toString('base64url'), privateKey: jwk.d };
}

/** The one statement that stores both keys when neither is there yet. */
export const INSERT_SQL = `INSERT INTO settings (name, value)
  SELECT 'vapid_public', ?1 WHERE NOT EXISTS (SELECT 1 FROM settings WHERE name IN ('vapid_public', 'vapid_private'))
  UNION ALL
  SELECT 'vapid_private', ?2 WHERE NOT EXISTS (SELECT 1 FROM settings WHERE name IN ('vapid_public', 'vapid_private'))`;

/**
 * Stores a fresh pair unless one is there. Returns "made" or "kept". Throws an Error whose
 * message names only the HTTP status, never the request.
 */
export async function ensureKeys({ token, account, database, base, fetch: send = fetch }) {
  const keys = makeKeys();
  const response = await send(`${base}/accounts/${account}/d1/database/${database}/query`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ sql: INSERT_SQL, params: [keys.publicKey, keys.privateKey] }),
  });
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok || body?.success !== true)
    throw new Error(`the D1 query answered HTTP ${response.status}`);
  const changes = body.result?.[0]?.meta?.changes ?? 0;
  return changes > 0 ? 'made' : 'kept';
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const token = process.env.CLOUDFLARE_API_TOKEN ?? '';
  const account = process.env.CLOUDFLARE_ACCOUNT_ID ?? '';
  const database = process.env.D1_DATABASE_ID ?? '';
  if (token === '' || account === '' || !/^[0-9a-f-]{36}$/.test(database)) {
    console.error('CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID and D1_DATABASE_ID must be set');
    process.exit(2);
  }
  try {
    const done = await ensureKeys({
      token,
      account,
      database,
      base: process.env.CLOUDFLARE_API_URL ?? 'https://api.cloudflare.com/client/v4',
    });
    process.stdout.write(`${done}\n`);
  } catch (error) {
    console.error(error instanceof Error ? error.message : 'the D1 query failed');
    process.exit(1);
  }
}
