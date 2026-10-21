/**
 * The key the browser sends in place of a password (LEAD ADDENDUM 1 of the
 * accounts spec): PBKDF2-SHA256 over the password, 600,000 iterations, 256
 * bits, base64url. The Worker never sees a password, and the free plan's 10 ms
 * of CPU per request is spent on nothing slow.
 *
 * The salt: an account has two keys, one for logging in by email and one for
 * logging in by username, each with its own random 16-byte salt made here at
 * sign-up; the Worker hands a login's salt back (POST /v1/login/salt) before
 * the key is derived. Unrelated salts keep an email and a username unlinkable
 * from outside. A v1 key (and the admin's, derived the same way by the deploy
 * runner, api/scripts/derive-key.mjs) is salted with SHA-256("snowlight-v1|"
 * + the login, trimmed and lowercased); `deriveKey` makes that one, and both
 * are checked against one test vector.
 */

export const ITERATIONS = 600_000;
export const MIN_PASSWORD = 8;
export const MAX_PASSWORD = 128;

/** The login a key is derived for: an email, a username or the admin's name, trimmed and lowercased. */
export function normalizeLogin(login: string): string {
  return login.trim().toLowerCase();
}

function base64url(bytes: ArrayBuffer | Uint8Array): string {
  let text = '';
  for (const byte of new Uint8Array(bytes)) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fromBase64url(text: string): Uint8Array<ArrayBuffer> {
  const padded =
    text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4);
  const raw = atob(padded);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

/** A fresh salt for a new key: 16 random bytes, base64url. */
export function randomSalt(
  random: (bytes: Uint8Array<ArrayBuffer>) => void = (b) => crypto.getRandomValues(b),
): string {
  const bytes = new Uint8Array(16);
  random(bytes);
  return base64url(bytes);
}

/** The key for a password with a salt the Worker handed back (base64url). */
export async function deriveWithSalt(
  salt: string,
  password: string,
  subtle: SubtleCrypto = crypto.subtle,
): Promise<string> {
  const base = await subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, [
    'deriveBits',
  ]);
  const bits = await subtle.deriveBits(
    { name: 'PBKDF2', hash: 'SHA-256', salt: fromBase64url(salt), iterations: ITERATIONS },
    base,
    256,
  );
  return base64url(bits);
}

/** The salt of a v1 key and of the admin's key: SHA-256("snowlight-v1|" + login), base64url. */
export async function loginSalt(
  login: string,
  subtle: SubtleCrypto = crypto.subtle,
): Promise<string> {
  const digest = await subtle.digest(
    'SHA-256',
    new TextEncoder().encode(`snowlight-v1|${normalizeLogin(login)}`),
  );
  return base64url(digest);
}

/** A v1 key: salted by the login itself. */
export async function deriveKey(
  login: string,
  password: string,
  subtle: SubtleCrypto = crypto.subtle,
): Promise<string> {
  return deriveWithSalt(await loginSalt(login, subtle), password, subtle);
}

/** The most common passwords, refused for a new password (any case). */
const COMMON = new Set([
  '12345678',
  '123456789',
  '1234567890',
  '11111111',
  '00000000',
  '87654321',
  '12341234',
  '11223344',
  '12121212',
  '88888888',
  '99999999',
  '66666666',
  '55555555',
  '22222222',
  'password',
  'password1',
  'password12',
  'password123',
  'passw0rd',
  'p@ssw0rd',
  'p@ssword',
  'qwertyui',
  'qwerty123',
  'qwertyuiop',
  '1q2w3e4r',
  '1qaz2wsx',
  'zaq12wsx',
  'asdfghjk',
  'asdf1234',
  'iloveyou',
  'iloveyou1',
  'sunshine',
  'princess',
  'football',
  'baseball',
  'basketball',
  'superman',
  'trustno1',
  'whatever',
  'starwars',
  'computer',
  'michelle',
  'jennifer',
  'charlie1',
  'letmein1',
  'welcome1',
  'welcome123',
  'abcd1234',
  'abc12345',
  'a1b2c3d4',
  'aa123456',
  'monkey12',
  'dragon12',
  'shadow12',
  'master12',
  'internet',
  'samsung1',
  'snowlight',
  'snowlight1',
  'snowday1',
  'snowdays',
  'schoolday',
  'changeme',
  'admin123',
  'administrator',
  'olivia123',
  'mustang1',
  'liverpool',
  'chelsea1',
  'pokemon1',
  'minecraft',
  'fortnite',
  'babygirl',
  'lovelove',
  'loveyou1',
  'soccer12',
  'hockey12',
  'hello123',
  'google123',
  'qazwsxedc',
  'zxcvbnm1',
  'zxcvbnmm',
  '1234qwer',
  'q1w2e3r4',
  'q1w2e3r4t5',
  '123qweasd',
  '123abc123',
  'aaaaaaaa',
  'abcdefgh',
  'abcdefg1',
]);

export type PasswordProblem = 'password_short' | 'password_long' | 'password_common';

/** How many characters a password has: code points, as the API's limits count them, not bytes. */
export function characters(text: string): number {
  let count = 0;
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    // A surrogate pair is one character.
    if (code >= 0xd800 && code <= 0xdbff && i + 1 < text.length) i++;
    count++;
  }
  return count;
}

/** What is wrong with a new password, or null. Length counts characters, not bytes. */
export function passwordProblem(password: string): PasswordProblem | null {
  const length = characters(password);
  if (length < MIN_PASSWORD) return 'password_short';
  if (length > MAX_PASSWORD) return 'password_long';
  if (COMMON.has(password.toLowerCase())) return 'password_common';
  return null;
}

/**
 * The characters a temporary password is made of: letters and digits without
 * look-alikes (no 0, 1, I, l or O), built from their codes since a password
 * is not words for the page.
 */
const PASSWORD_CODES: readonly number[] = (() => {
  const codes: number[] = [];
  const add = (from: number, to: number): void => {
    for (let code = from; code <= to; code++) codes.push(code);
  };
  add(0x32, 0x39); // 2-9
  add(0x41, 0x5a); // A-Z
  add(0x61, 0x7a); // a-z
  const lookAlikes = new Set([0x49, 0x4f, 0x6c, 0x6f]); // I, O, l, o
  return codes.filter((code) => !lookAlikes.has(code));
})();

/** A temporary password for an admin's reset: 16 characters, each equally likely. */
export function temporaryPassword(
  random: (bytes: Uint8Array<ArrayBuffer>) => void = (b) => crypto.getRandomValues(b),
): string {
  const codes: number[] = [];
  const bytes = new Uint8Array(1);
  const limit = 256 - (256 % PASSWORD_CODES.length);
  while (codes.length < 16) {
    random(bytes);
    const byte = bytes[0] ?? limit;
    // Rejection sampling keeps every character equally likely.
    if (byte < limit) codes.push(PASSWORD_CODES[byte % PASSWORD_CODES.length] ?? 0x32);
  }
  return String.fromCharCode(...codes);
}
