/**
 * The signed-in account: its session token (kept in localStorage where the
 * browser allows it), the user the API last returned, and the calls that
 * change them. Nothing shows until the API answers its health check, so a
 * build whose API is down or not deployed yet shows no account controls.
 */

import { ApiError, type Api } from './api';
import { characters, deriveKey, normalizeLogin, passwordProblem } from './key';

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
}

export interface AccountState {
  /** The API answered its health check: the account controls show. */
  readonly available: boolean;
  /** Settled: the stored session, if any, has been checked. */
  readonly ready: boolean;
  readonly user: User | null;
}

/** What the account sheet shows. */
export type SheetView = 'signup' | 'login' | 'schools' | 'settings';

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
  signup(name: string, email: string, password: string, over13: boolean): Promise<void>;
  login(login: string, password: string): Promise<void>;
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
  readonly derive?: (login: string, password: string) => Promise<string>;
}

export function createAccountStore(api: Api, options: AccountOptions = {}): AccountStore {
  const derive = options.derive ?? deriveKey;
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
    async signup(name, email, password, over13) {
      const problem = passwordProblem(password);
      if (problem !== null) throw new ApiError(problem, 400);
      if (!over13) throw new ApiError('over13_required', 400);
      const key = await derive(email, password);
      signIn(
        await api.call('POST', '/v1/signup', {
          name: name.trim(),
          email: normalizeLogin(email),
          key,
          over13: true,
        }),
      );
    },
    async login(login, password) {
      if (password.length === 0 || characters(password) > 128) throw new ApiError('bad_login', 401);
      const key = await derive(login, password);
      signIn(await api.call('POST', '/v1/login', { login: normalizeLogin(login), key }));
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
        // The key follows the login: a new email needs the password to derive it again.
        const login = user.email ?? '';
        body.current_key = await derive(login, current);
        body.new_key = await derive(email ?? login, change.newPassword ?? current);
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
      const key = await derive(user.email ?? '', password);
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
