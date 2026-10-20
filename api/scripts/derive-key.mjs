// Derives the key the browser sends for a login and password, exactly as
// web/src/account/key.ts does: PBKDF2-SHA256 over the password with salt
// SHA-256("snowlight-v1|" + login, trimmed and lowercased), 600,000
// iterations, 256 bits, base64url. The deploy workflow (api.yml) runs it with
// the ADMIN_PASSWORD secret in the environment and pipes the key straight into
// `wrangler secret put ADMIN_KEY`, so the password never leaves the runner and
// neither value is printed. Usage: DERIVE_LOGIN=olivia DERIVE_PASSWORD=... node scripts/derive-key.mjs

import { webcrypto } from 'node:crypto';

export const ITERATIONS = 600_000;

export async function deriveKey(login, password) {
  const enc = new TextEncoder();
  const salt = await webcrypto.subtle.digest(
    'SHA-256',
    enc.encode(`snowlight-v1|${login.trim().toLowerCase()}`),
  );
  const base = await webcrypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, [
    'deriveBits',
  ]);
  const bits = await webcrypto.subtle.deriveBits(
    { name: 'PBKDF2', hash: 'SHA-256', salt, iterations: ITERATIONS },
    base,
    256,
  );
  return Buffer.from(bits).toString('base64url');
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const login = process.env.DERIVE_LOGIN ?? '';
  const password = process.env.DERIVE_PASSWORD ?? '';
  if (login.trim() === '' || password === '') {
    console.error('DERIVE_LOGIN and DERIVE_PASSWORD must both be set');
    process.exit(2);
  }
  process.stdout.write(await deriveKey(login, password));
}
