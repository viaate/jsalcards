/** Calls to the accounts API: JSON in and out, the session token as a bearer token. */

export class ApiError extends Error {
  constructor(
    /** The API's error code ("bad_login", "too_many"…), "network" or "server". */
    readonly code: string,
    readonly status: number,
  ) {
    super(code);
  }
}

export interface Api {
  readonly root: string;
  call<T>(method: string, path: string, body?: unknown, token?: string | null): Promise<T>;
}

export function createApi(root: string, fetcher: typeof fetch = (...args) => fetch(...args)): Api {
  return {
    root,
    async call<T>(method: string, path: string, body?: unknown, token?: string | null): Promise<T> {
      const headers: Record<string, string> = {};
      if (body !== undefined) headers['Content-Type'] = 'application/json';
      if (token) headers.Authorization = `Bearer ${token}`;
      let response: Response;
      try {
        response = await fetcher(`${root}${path}`, {
          method,
          headers,
          body: body === undefined ? null : JSON.stringify(body),
          // Never the HTTP cache: an account's answers are always read fresh.
          cache: 'no-store',
          credentials: 'omit',
          mode: 'cors',
        });
      } catch {
        throw new ApiError('network', 0);
      }
      let parsed: unknown;
      try {
        parsed = await response.json();
      } catch {
        parsed = null;
      }
      if (!response.ok) {
        const code =
          typeof parsed === 'object' && parsed !== null && 'error' in parsed
            ? String(parsed.error)
            : 'server';
        throw new ApiError(response.status >= 500 ? 'server' : code, response.status);
      }
      if (parsed === null) throw new ApiError('server', response.status);
      return parsed as T;
    },
  };
}
