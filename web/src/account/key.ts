/**
 * The key the browser sends in place of a password (LEAD ADDENDUM 1 of the
 * accounts spec): PBKDF2-SHA256 over the password, salted with
 * SHA-256("snowlight-v1|" + the login, trimmed and lowercased), 600,000
 * iterations, 256 bits, base64url. The Worker never sees a password, and the
 * free plan's 10 ms of CPU per request is spent on nothing slow. The deploy
 * runner derives the admin's key the same way (api/scripts/derive-key.mjs);
 * both are checked against one test vector.
 */

export const ITERATIONS = 600_000;
export const MIN_PASSWORD = 8;
export const MAX_PASSWORD = 128;

/** The login a key is derived for: an email, or the admin's name, trimmed and lowercased. */
export function normalizeLogin(login: string): string {
  return login.trim().toLowerCase();
}

function base64url(bytes: ArrayBuffer): string {
  let text = '';
  for (const byte of new Uint8Array(bytes)) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export async function deriveKey(
  login: string,
  password: string,
  subtle: SubtleCrypto = crypto.subtle,
): Promise<string> {
  const encoder = new TextEncoder();
  const salt = await subtle.digest(
    'SHA-256',
    encoder.encode(`snowlight-v1|${normalizeLogin(login)}`),
  );
  const base = await subtle.importKey('raw', encoder.encode(password), 'PBKDF2', false, [
    'deriveBits',
  ]);
  const bits = await subtle.deriveBits(
    { name: 'PBKDF2', hash: 'SHA-256', salt, iterations: ITERATIONS },
    base,
    256,
  );
  return base64url(bits);
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
