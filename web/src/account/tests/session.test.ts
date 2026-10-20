import { beforeEach, describe, expect, it } from 'vitest';

import { ApiError, type Api } from '../api';
import { TOKEN_KEY, createAccountStore, type User } from '../session';

const TOKEN = 'a'.repeat(43);
const NEW_TOKEN = 'b'.repeat(43);

const user = (over: Partial<User> = {}): User => ({
  id: 'u1',
  name: 'Sam Rivera',
  email: 'sam@example.com',
  role: 'user',
  schools: [],
  created_at: '2026-10-20T00:00:00.000Z',
  ...over,
});

interface Call {
  method: string;
  path: string;
  body: unknown;
  token: string | null | undefined;
}

function fakeApi(answer: (call: Call) => unknown): Api & { calls: Call[] } {
  const calls: Call[] = [];
  return {
    root: 'https://api.test',
    calls,
    call<T>(method: string, path: string, body?: unknown, token?: string | null): Promise<T> {
      const call = { method, path, body, token };
      calls.push(call);
      try {
        return Promise.resolve(answer(call) as T);
      } catch (error) {
        return Promise.reject(error instanceof Error ? error : new Error(String(error)));
      }
    },
  };
}

const derive = (login: string, password: string): Promise<string> =>
  Promise.resolve(`key(${login.trim().toLowerCase()}|${password})`);

beforeEach(() => {
  localStorage.clear();
});

describe('the account store', () => {
  it('stays hidden when the API does not answer', async () => {
    const api = fakeApi(() => {
      throw new ApiError('network', 0);
    });
    const store = createAccountStore(api, { derive });
    await store.start();
    expect(store.state).toEqual({ available: false, ready: true, user: null });
  });

  it('shows signed out when the API answers and there is no session', async () => {
    const api = fakeApi(() => ({ ok: true }));
    const store = createAccountStore(api, { derive });
    await store.start();
    expect(store.state.available).toBe(true);
    expect(store.state.user).toBeNull();
    expect(api.calls.map((c) => c.path)).toEqual(['/v1/health']);
  });

  it('restores a stored session, and drops one the API no longer knows', async () => {
    localStorage.setItem(TOKEN_KEY, TOKEN);
    const known = createAccountStore(
      fakeApi((c) => (c.path === '/v1/me' ? { user: user() } : { ok: true })),
      { derive },
    );
    await known.start();
    expect(known.state.user?.name).toBe('Sam Rivera');

    const gone = createAccountStore(
      fakeApi((c) => {
        if (c.path === '/v1/me') throw new ApiError('signed_out', 401);
        return { ok: true };
      }),
      { derive },
    );
    await gone.start();
    expect(gone.state.user).toBeNull();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it('signs up with a derived key, never the password', async () => {
    const api = fakeApi((c) => (c.path === '/v1/signup' ? { token: TOKEN, user: user() } : {}));
    const store = createAccountStore(api, { derive });
    await store.signup(' Sam Rivera ', 'Sam@Example.com', 'snow day on tuesday', true);
    const call = api.calls.find((c) => c.path === '/v1/signup');
    expect(call?.body).toEqual({
      name: 'Sam Rivera',
      email: 'sam@example.com',
      key: 'key(sam@example.com|snow day on tuesday)',
      over13: true,
    });
    expect(JSON.stringify(api.calls)).not.toContain('"snow day on tuesday"');
    expect(localStorage.getItem(TOKEN_KEY)).toBe(TOKEN);
    expect(store.state.user?.email).toBe('sam@example.com');
  });

  it('refuses weak passwords and no age confirmation before calling', async () => {
    const api = fakeApi(() => ({}));
    const store = createAccountStore(api, { derive });
    await expect(store.signup('A', 'a@b.co', 'short', true)).rejects.toMatchObject({
      code: 'password_short',
    });
    await expect(store.signup('A', 'a@b.co', 'password123', true)).rejects.toMatchObject({
      code: 'password_common',
    });
    await expect(store.signup('A', 'a@b.co', 'snow day on tuesday', false)).rejects.toMatchObject({
      code: 'over13_required',
    });
    expect(api.calls).toEqual([]);
  });

  it('logs in and out', async () => {
    const api = fakeApi((c) => (c.path === '/v1/login' ? { token: TOKEN, user: user() } : {}));
    const store = createAccountStore(api, { derive });
    await store.login(' Olivia ', 'pw');
    expect(api.calls[0]?.body).toEqual({ login: 'olivia', key: 'key(olivia|pw)' });
    await store.logout();
    expect(store.state.user).toBeNull();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(api.calls[1]).toMatchObject({ path: '/v1/logout', token: TOKEN });
  });

  it('changes email with keys derived for the old and new email, and takes the new token', async () => {
    const api = fakeApi((c) => {
      if (c.path === '/v1/login') return { token: TOKEN, user: user() };
      if (c.path === '/v1/me')
        return { token: NEW_TOKEN, user: user({ email: 'new@example.com' }) };
      return {};
    });
    const store = createAccountStore(api, { derive });
    await store.login('sam@example.com', 'pw');
    await store.update({ email: 'New@Example.com', currentPassword: 'pw' });
    expect(api.calls[1]?.body).toEqual({
      email: 'new@example.com',
      current_key: 'key(sam@example.com|pw)',
      new_key: 'key(new@example.com|pw)',
    });
    expect(localStorage.getItem(TOKEN_KEY)).toBe(NEW_TOKEN);
  });

  it('signs out when a call comes back signed out', async () => {
    const api = fakeApi((c) => {
      if (c.path === '/v1/login') return { token: TOKEN, user: user() };
      throw new ApiError('signed_out', 401);
    });
    const store = createAccountStore(api, { derive });
    await store.login('sam@example.com', 'pw');
    await expect(store.setSchools([])).rejects.toBeInstanceOf(ApiError);
    expect(store.state.user).toBeNull();
  });
});
