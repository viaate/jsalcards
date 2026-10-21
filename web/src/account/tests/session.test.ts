import { beforeEach, describe, expect, it } from 'vitest';

import { ApiError, type Api } from '../api';
import { loginSalt } from '../key';
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
  username: 'sam_r',
  join_number: 2,
  username_required: false,
  renamed: false,
  needs_rekey: false,
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
      // The Worker's salt for a login: here, its name.
      if (path === '/v1/login/salt')
        return Promise.resolve({ salt: `srv:${(body as { login: string }).login}` } as T);
      try {
        return Promise.resolve(answer(call) as T);
      } catch (error) {
        return Promise.reject(error instanceof Error ? error : new Error(String(error)));
      }
    },
  };
}

const derive = (salt: string, password: string): Promise<string> =>
  Promise.resolve(`key(${salt}|${password})`);
let salts = 0;
const salt = (): string => `s${String(++salts)}`;
const opts = () => ({ derive, salt });

beforeEach(() => {
  localStorage.clear();
  salts = 0;
});

describe('the account store', () => {
  it('stays hidden when the API does not answer', async () => {
    const api = fakeApi(() => {
      throw new ApiError('network', 0);
    });
    const store = createAccountStore(api, opts());
    await store.start();
    expect(store.state).toEqual({ available: false, ready: true, user: null });
  });

  it('shows signed out when the API answers and there is no session', async () => {
    const api = fakeApi(() => ({ ok: true }));
    const store = createAccountStore(api, opts());
    await store.start();
    expect(store.state.available).toBe(true);
    expect(store.state.user).toBeNull();
    expect(api.calls.map((c) => c.path)).toEqual(['/v1/health']);
  });

  it('restores a stored session, and drops one the API no longer knows', async () => {
    localStorage.setItem(TOKEN_KEY, TOKEN);
    const known = createAccountStore(
      fakeApi((c) => (c.path === '/v1/me' ? { user: user() } : { ok: true })),
      opts(),
    );
    await known.start();
    expect(known.state.user?.name).toBe('Sam Rivera');

    const gone = createAccountStore(
      fakeApi((c) => {
        if (c.path === '/v1/me') throw new ApiError('signed_out', 401);
        return { ok: true };
      }),
      opts(),
    );
    await gone.start();
    expect(gone.state.user).toBeNull();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it('signs up with two derived keys, the email one with its v1 salt, never the password', async () => {
    const api = fakeApi((c) => (c.path === '/v1/signup' ? { token: TOKEN, user: user() } : {}));
    const store = createAccountStore(api, opts());
    await store.signup(' Sam Rivera ', 'Sam@Example.com', 'Sam_R', 'snow day on tuesday', true);
    const call = api.calls.find((c) => c.path === '/v1/signup');
    const v1 = await loginSalt('sam@example.com');
    expect(call?.body).toEqual({
      name: 'Sam Rivera',
      email: 'sam@example.com',
      username: 'sam_r',
      key: `key(${v1}|snow day on tuesday)`,
      email_salt: v1,
      name_key: 'key(s1|snow day on tuesday)',
      name_salt: 's1',
      over13: true,
    });
    // No salt is asked for: the email's is made here.
    expect(api.calls.map((c) => c.path)).toEqual(['/v1/signup']);
    expect(JSON.stringify(api.calls)).not.toContain('"snow day on tuesday"');
    expect(localStorage.getItem(TOKEN_KEY)).toBe(TOKEN);
    expect(store.state.user?.email).toBe('sam@example.com');
  });

  it('refuses weak passwords and no age confirmation before calling', async () => {
    const api = fakeApi(() => ({}));
    const store = createAccountStore(api, opts());
    await expect(store.signup('A', 'a@b.co', 'abc', 'short', true)).rejects.toMatchObject({
      code: 'password_short',
    });
    await expect(store.signup('A', 'a@b.co', 'abc', 'password123', true)).rejects.toMatchObject({
      code: 'password_common',
    });
    await expect(
      store.signup('A', 'a@b.co', 'abc', 'snow day on tuesday', false),
    ).rejects.toMatchObject({ code: 'over13_required' });
    expect(api.calls).toEqual([]);
  });

  it('logs in by username or the admin name with the salt the Worker hands back, and by email with its v1 salt', async () => {
    const api = fakeApi((c) => (c.path === '/v1/login' ? { token: TOKEN, user: user() } : {}));
    const store = createAccountStore(api, opts());
    await store.login(' Olivia ', 'pw');
    expect(api.calls[0]).toMatchObject({ path: '/v1/login/salt', body: { login: 'olivia' } });
    expect(api.calls[1]?.body).toEqual({ login: 'olivia', key: 'key(srv:olivia|pw)' });
    await store.login('Sam_R', 'pw');
    expect(api.calls[3]?.body).toEqual({ login: 'sam_r', key: 'key(srv:sam_r|pw)' });
    await store.login('Sam@Example.com', 'pw');
    expect(api.calls[4]?.body).toEqual({
      login: 'sam@example.com',
      key: `key(${await loginSalt('sam@example.com')}|pw)`,
    });
    await store.logout();
    expect(store.state.user).toBeNull();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(api.calls[5]).toMatchObject({ path: '/v1/logout', token: TOKEN });
  });

  it('gives a v1 account fresh keys right after it logs in', async () => {
    const api = fakeApi((c) => {
      if (c.path === '/v1/login')
        return { token: TOKEN, user: user({ needs_rekey: true, username: null }) };
      if (c.path === '/v1/me')
        return { token: NEW_TOKEN, user: user({ username: null, username_required: true }) };
      return {};
    });
    const store = createAccountStore(api, opts());
    await store.login('sam@example.com', 'pw');
    const v1 = await loginSalt('sam@example.com');
    expect(api.calls[1]).toMatchObject({
      method: 'PATCH',
      path: '/v1/me',
      body: {
        current_key: `key(${v1}|pw)`,
        new_key: `key(${v1}|pw)`,
        email_salt: v1,
        name_key: 'key(s1|pw)',
        name_salt: 's1',
      },
    });
    expect(store.state.user?.needs_rekey).toBe(false);
    expect(localStorage.getItem(TOKEN_KEY)).toBe(NEW_TOKEN);
  });

  it('checks and picks a username, asking a v1 account for its password first', async () => {
    const api = fakeApi((c) => {
      if (c.path === '/v1/login') return { token: TOKEN, user: user() };
      if (c.path.startsWith('/v1/usernames/check')) return { ok: true, username: 'new_name' };
      if (c.path === '/v1/me/username') return { user: user({ username: 'new_name' }) };
      return {};
    });
    const store = createAccountStore(api, opts());
    expect(await store.checkUsername('New Name')).toEqual({ ok: true, username: 'new_name' });
    expect(api.calls[0]?.path).toBe('/v1/usernames/check?name=new%20name');
    await store.login('sam@example.com', 'pw');
    await store.pickUsername('New_Name');
    expect(api.calls.at(-1)).toMatchObject({ method: 'PUT', body: { username: 'new_name' } });
    expect(store.state.user?.username).toBe('new_name');
  });

  it('changes email with the current key and fresh keys, and takes the new token', async () => {
    const api = fakeApi((c) => {
      if (c.path === '/v1/login') return { token: TOKEN, user: user() };
      if (c.path === '/v1/me')
        return { token: NEW_TOKEN, user: user({ email: 'new@example.com' }) };
      return {};
    });
    const store = createAccountStore(api, opts());
    await store.login('sam@example.com', 'pw');
    await store.update({ email: 'New@Example.com', currentPassword: 'pw' });
    const [old, fresh] = [await loginSalt('sam@example.com'), await loginSalt('new@example.com')];
    expect(api.calls.at(-1)?.body).toEqual({
      email: 'new@example.com',
      current_key: `key(${old}|pw)`,
      new_key: `key(${fresh}|pw)`,
      email_salt: fresh,
      name_key: 'key(s1|pw)',
      name_salt: 's1',
    });
    expect(localStorage.getItem(TOKEN_KEY)).toBe(NEW_TOKEN);
  });

  it('signs out when a call comes back signed out', async () => {
    const api = fakeApi((c) => {
      if (c.path === '/v1/login') return { token: TOKEN, user: user() };
      throw new ApiError('signed_out', 401);
    });
    const store = createAccountStore(api, opts());
    await store.login('sam@example.com', 'pw');
    await expect(store.setSchools([])).rejects.toBeInstanceOf(ApiError);
    expect(store.state.user).toBeNull();
  });
});
