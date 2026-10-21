/**
 * The signed-in account: its session token (kept in localStorage where the
 * browser allows it), the user the API last returned, and the calls that
 * change them. Nothing shows until the API answers its health check, so a
 * build whose API is down or not deployed yet shows no account controls.
 */

import { ApiError, type Api } from './api';
import {
  characters,
  deriveWithSalt,
  loginSalt,
  normalizeLogin,
  passwordProblem,
  randomSalt,
} from './key';

export const TOKEN_KEY = 'snowlight:session';
export const MAX_SCHOOLS = 5;

export interface SavedSchool {
  readonly id: string;
  readonly name: string;
}

export interface User {
  readonly id: string;
  readonly name: string;
  readonly email: string | null;
  readonly role: 'user' | 'admin';
  readonly schools: readonly SavedSchool[];
  readonly created_at: string;
  /** Lowercase a-z 0-9 _; null until the account picks one. */
  readonly username: string | null;
  /** #0001-#9999 in sign-up order; null after #9999. */
  readonly join_number: number | null;
  /** No username yet, or the admin changed it: the account picks one before anything else. */
  readonly username_required: boolean;
  /** The admin changed the username. */
  readonly renamed: boolean;
  /** The account's keys predate usernames: fresh ones are derived while the password is at hand. */
  readonly needs_rekey: boolean;
}

/** What the live check says of a username. */
export type UsernameCheck =
  | { readonly ok: true; readonly username: string }
  | { readonly ok: false; readonly problem: string };

export interface AccountState {
  /** The API answered its health check: the account controls show. */
  readonly available: boolean;
  /** Settled: the stored session, if any, has been checked. */
  readonly ready: boolean;
  readonly user: User | null;
}

/** What the account sheet shows. */
export type SheetView = 'signup' | 'login' | 'schools' | 'settings' | 'username';

export type AccountListener = (state: AccountState) => void;

export interface ProfileChange {
  readonly name?: string;
  readonly email?: string;
  readonly currentPassword?: string;
  readonly newPassword?: string;
}

export interface AccountStore {
  readonly state: AccountState;
  readonly api: Api;
  /** The session token, for admin calls. */
  token(): string | null;
  subscribe(listener: AccountListener): () => void;
  /** Checks the API and the stored session. */
  start(): Promise<void>;
  signup(
    name: string,
    email: string,
    username: string,
    password: string,
    over13: boolean,
  ): Promise<void>;
  /** Logs in by email, username or the admin's name. */
  login(login: string, password: string): Promise<void>;
  /** Whether a username may be taken now (format, lists and availability). */
  checkUsername(username: string): Promise<UsernameCheck>;
  /** Picks a username (a new account's first, or after the admin changed it). */
  pickUsername(username: string, password?: string): Promise<void>;
  logout(): Promise<void>;
  update(change: ProfileChange): Promise<void>;
  deleteAccount(password: string): Promise<void>;
  setSchools(schools: readonly SavedSchool[]): Promise<void>;
  /** A call came back signed out: the session is gone. */
  signedOut(): void;
}

interface Storage_ {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function storage(): Storage_ | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function readToken(): string | null {
  try {
    const token = storage()?.getItem(TOKEN_KEY) ?? null;
    return token !== null && /^[A-Za-z0-9_-]{43}$/.test(token) ? token : null;
  } catch {
    return null;
  }
}

function writeToken(token: string | null): void {
  try {
    const store = storage();
    if (token === null) store?.removeItem(TOKEN_KEY);
    else store?.setItem(TOKEN_KEY, token);
  } catch {
    // Private windows and blocked storage: the session lasts while the page is open.
  }
}

export interface AccountOptions {
  /** The slow key derivation (key.ts deriveWithSalt), replaceable in tests. */
  readonly derive?: (salt: string, password: string) => Promise<string>;
  /** A fresh random salt (key.ts randomSalt). */
  readonly salt?: () => string;
}

/**
 * The keys a sign-up or a password change sends: the email key, salted with
 * the email's v1 salt (key.ts loginSalt), and the username key with a fresh
 * random salt.
 */
interface FreshKeys {
  readonly key: string;
  readonly email_salt: string;
  readonly name_key: string;
  readonly name_salt: string;
}

export function createAccountStore(api: Api, options: AccountOptions = {}): AccountStore {
  const derive = options.derive ?? deriveWithSalt;
  const newSalt = options.salt ?? randomSalt;
  const listeners = new Set<AccountListener>();
  let token = readToken();
  let state: AccountState = { available: false, ready: false, user: null };

  const set = (next: Partial<AccountState>): void => {
    state = { ...state, ...next };
    for (const listener of [...listeners]) listener(state);
  };

  const signIn = (next: { token: string; user: User }): void => {
    token = next.token;
    writeToken(token);
    set({ user: next.user });
  };

  const clear = (): void => {
    token = null;
    writeToken(null);
    set({ user: null });
  };

  /** A call with the session; a 401 signs the page out. */
  const authed = async <T>(method: string, path: string, body?: unknown): Promise<T> => {
    try {
      return await api.call<T>(method, path, body, token);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) clear();
      throw error;
    }
  };

  /**
   * The salt of a login's key: an email's is its v1 salt, made here; a
   * username's is the one the Worker keeps (a made-up steady one for a
   * username it does not know).
   */
  const saltFor = async (login: string): Promise<string> =>
    login.includes('@')
      ? loginSalt(login)
      : (
          await api.call<{ salt: string }>('POST', '/v1/login/salt', {
            login: normalizeLogin(login),
          })
        ).salt;

  const freshKeys = async (password: string, email: string): Promise<FreshKeys> => {
    const emailSalt = await loginSalt(email);
    const nameSalt = newSalt();
    const [key, nameKey] = await Promise.all([
      derive(emailSalt, password),
      derive(nameSalt, password),
    ]);
    return { key, email_salt: emailSalt, name_key: nameKey, name_salt: nameSalt };
  };

  /** The signed-in account's current email key, for a change that needs the password. */
  const currentKey = async (password: string): Promise<string> => {
    const email = state.user?.email ?? '';
    return derive(await saltFor(email), password);
  };

  /** A v1 account's fresh keys, made with the password it just gave (the same password). */
  const rekey = async (current: string, password: string, email: string): Promise<void> => {
    const keys = await freshKeys(password, email);
    const result = await authed<{ token?: string; user: User }>('PATCH', '/v1/me', {
      current_key: current,
      new_key: keys.key,
      email_salt: keys.email_salt,
      name_key: keys.name_key,
      name_salt: keys.name_salt,
    });
    if (result.token !== undefined) {
      token = result.token;
      writeToken(token);
    }
    set({ user: result.user });
  };

  const store: AccountStore = {
    get state() {
      return state;
    },
    api,
    token: () => token,
    subscribe(listener) {
      listeners.add(listener);
      listener(state);
      return () => listeners.delete(listener);
    },
    async start() {
      try {
        await api.call('GET', '/v1/health');
      } catch {
        set({ available: false, ready: true });
        return;
      }
      if (token === null) {
        set({ available: true, ready: true });
        return;
      }
      try {
        const { user } = await api.call<{ user: User }>('GET', '/v1/me', undefined, token);
        set({ available: true, ready: true, user });
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) clear();
        set({ available: true, ready: true });
      }
    },
    async signup(name, email, username, password, over13) {
      const problem = passwordProblem(password);
      if (problem !== null) throw new ApiError(problem, 400);
      if (!over13) throw new ApiError('over13_required', 400);
      const keys = await freshKeys(password, email);
      signIn(
        await api.call('POST', '/v1/signup', {
          name: name.trim(),
          email: normalizeLogin(email),
          username: normalizeLogin(username),
          ...keys,
          over13: true,
        }),
      );
    },
    async login(login, password) {
      if (password.length === 0 || characters(password) > 128) throw new ApiError('bad_login', 401);
      const salt = await saltFor(login);
      const key = await derive(salt, password);
      const result = await api.call<{ token: string; user: User }>('POST', '/v1/login', {
        login: normalizeLogin(login),
        key,
      });
      // A v1 account gets its fresh keys now, while the password is at hand, before the page
      // shows it signed in. If this fails, the username view asks for the password again.
      if (result.user.needs_rekey && result.user.role === 'user') {
        token = result.token;
        writeToken(token);
        try {
          await rekey(key, password, result.user.email ?? '');
          return;
        } catch {
          // Signed in either way.
        }
      }
      signIn(result);
    },
    async checkUsername(username) {
      const name = encodeURIComponent(normalizeLogin(username));
      return api.call<UsernameCheck>('GET', `/v1/usernames/check?name=${name}`);
    },
    async pickUsername(username, password) {
      const user = state.user;
      if (user === null) throw new ApiError('signed_out', 401);
      if (user.needs_rekey) {
        if (password === undefined || password.length === 0)
          throw new ApiError('wrong_password', 403);
        await rekey(await currentKey(password), password, user.email ?? '');
      }
      const result = await authed<{ user: User }>('PUT', '/v1/me/username', {
        username: normalizeLogin(username),
      });
      set({ user: result.user });
    },
    async logout() {
      const held = token;
      clear();
      if (held === null) return;
      try {
        await api.call('POST', '/v1/logout', undefined, held);
      } catch {
        // Signed out here either way; the session ends on its own in 30 days.
      }
    },
    async update(change) {
      const user = state.user;
      if (user === null) throw new ApiError('signed_out', 401);
      const body: Record<string, unknown> = {};
      if (change.name !== undefined) body.name = change.name.trim();
      const email =
        change.email !== undefined && normalizeLogin(change.email) !== (user.email ?? '')
          ? normalizeLogin(change.email)
          : undefined;
      if (email !== undefined || change.newPassword !== undefined) {
        const current = change.currentPassword ?? '';
        if (change.newPassword !== undefined) {
          const problem = passwordProblem(change.newPassword);
          if (problem !== null) throw new ApiError(problem, 400);
        }
        // Fresh keys for both logins, from the new password (or the same one for a new email).
        body.current_key = await currentKey(current);
        const keys = await freshKeys(change.newPassword ?? current, email ?? user.email ?? '');
        body.new_key = keys.key;
        body.email_salt = keys.email_salt;
        body.name_key = keys.name_key;
        body.name_salt = keys.name_salt;
        if (email !== undefined) body.email = email;
      }
      const result = await authed<{ token?: string; user: User }>('PATCH', '/v1/me', body);
      if (result.token !== undefined) {
        token = result.token;
        writeToken(token);
      }
      set({ user: result.user });
    },
    async deleteAccount(password) {
      const user = state.user;
      if (user === null) throw new ApiError('signed_out', 401);
      const key = await currentKey(password);
      await authed('DELETE', '/v1/me', { key });
      clear();
    },
    async setSchools(schools) {
      if (state.user === null) return;
      const { user } = await authed<{ user: User }>('PUT', '/v1/me/schools', {
        schools: schools.slice(0, MAX_SCHOOLS),
      });
      set({ user });
    },
    signedOut: clear,
  };
  return store;
}
