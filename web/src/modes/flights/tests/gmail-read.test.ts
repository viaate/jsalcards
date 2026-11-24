/**
 * The demo Gmail read's grant (flights spec D19 GOOGLE RULE) against a made-up Google Identity
 * Services object and a made-up Gmail: it asks for gmail.readonly alone on the demo's own client,
 * and always revokes that grant when it is done (its own client: no Connect Google link is on it).
 */
import { afterEach, describe, expect, it } from 'vitest';

import { LEFTOVER_KEY, revokeLeftover } from '../gmail-leftover';
import { readGmail } from '../gmail-read';

interface Asked {
  client_id?: string | undefined;
  scope: string;
  include_granted_scopes?: boolean | undefined;
}

function fakeGoogle(): { asked: Asked[]; revoked: string[] } {
  const asked: Asked[] = [];
  const revoked: string[] = [];
  (window as { google?: unknown }).google = {
    accounts: {
      oauth2: {
        initTokenClient(config: Asked & { callback: (answer: { access_token: string }) => void }) {
          asked.push({
            client_id: config.client_id,
            scope: config.scope,
            include_granted_scopes: config.include_granted_scopes,
          });
          return {
            requestAccessToken: () => {
              config.callback({ access_token: 'demo-token' });
            },
          };
        },
        revoke(token: string) {
          revoked.push(token);
        },
      },
    },
  };
  return { asked, revoked };
}

const noMail: typeof fetch = () =>
  Promise.resolve(new Response(JSON.stringify({ messages: [] }), { status: 200 }));

afterEach(() => {
  delete (window as { google?: unknown }).google;
  window.sessionStorage.clear();
});

describe('the demo Gmail read', () => {
  it('asks for gmail.readonly alone on the client it is given, never with granted scopes', async () => {
    const { asked } = fakeGoogle();
    await readGmail('demo-client', new Map(), noMail);
    expect(asked).toEqual([
      {
        client_id: 'demo-client',
        scope: 'https://www.googleapis.com/auth/gmail.readonly',
        include_granted_scopes: false,
      },
    ]);
  });

  it('always revokes its grant when it is done, also when the read fails', async () => {
    const { revoked } = fakeGoogle();
    await readGmail('demo-client', new Map(), noMail);
    expect(revoked).toEqual(['demo-token']);
    const failing: typeof fetch = () => Promise.resolve(new Response('', { status: 500 }));
    await expect(readGmail('demo-client', new Map(), failing)).rejects.toThrow();
    expect(revoked).toEqual(['demo-token', 'demo-token']);
  });
  it('revokes a grant a cut-off read left, on the next load or read (SAFE-R3-S3)', async () => {
    const posted: { url: string; body: string }[] = [];
    const fetcher: typeof fetch = (url, init) => {
      posted.push({
        url: typeof url === 'string' ? url : '',
        body: typeof init?.body === 'string' ? init.body : '',
      });
      return Promise.resolve(new Response(JSON.stringify({ messages: [] }), { status: 200 }));
    };
    // Nothing left: nothing is sent.
    expect(await revokeLeftover(fetcher)).toBe(false);
    expect(posted).toEqual([]);
    // A read keeps its token only while it runs.
    const { revoked } = fakeGoogle();
    let during: string | null = null;
    await readGmail('5678-demo.apps.googleusercontent.com', new Map(), (url, init) => {
      during = window.sessionStorage.getItem(LEFTOVER_KEY);
      return fetcher(url, init);
    });
    expect(during).toBe(JSON.stringify(['demo-token']));
    expect(window.sessionStorage.getItem(LEFTOVER_KEY)).toBeNull();
    expect(revoked).toEqual(['demo-token']);
    // A reload in the middle of a read left one: the next load revokes it, once.
    posted.length = 0;
    window.sessionStorage.setItem(LEFTOVER_KEY, 'cut-off-token');
    expect(await revokeLeftover(fetcher)).toBe(true);
    expect(posted).toEqual([
      { url: 'https://oauth2.googleapis.com/revoke', body: 'token=cut-off-token' },
    ]);
    expect(window.sessionStorage.getItem(LEFTOVER_KEY)).toBeNull();
    expect(await revokeLeftover(fetcher)).toBe(false);
  });

  it('never cuts off a read still running in this page when My trips opens again', async () => {
    // SAFE-R4-S2: the mount's revoke is for a token an earlier page load left, not this one's.
    window.sessionStorage.removeItem(LEFTOVER_KEY);
    const { revoked } = fakeGoogle();
    const posted: string[] = [];
    let atMount: boolean | null = null;
    const found = await readGmail(
      '5678-demo.apps.googleusercontent.com',
      new Map(),
      async (url) => {
        const href = typeof url === 'string' ? url : '';
        posted.push(href);
        // My trips mounts again while the read runs.
        if (href.includes('/messages?') && atMount === null)
          atMount = await revokeLeftover((u) => {
            posted.push(typeof u === 'string' ? u : '');
            return Promise.resolve(new Response('', { status: 200 }));
          });
        return new Response(JSON.stringify({ messages: [] }), { status: 200 });
      },
    );
    expect(found).toEqual([]);
    expect(atMount).toBe(false);
    expect(posted.some((u) => u.includes('/revoke'))).toBe(false);
    // Revoked once, by the read itself, at its end.
    expect(revoked).toEqual(['demo-token']);
    expect(window.sessionStorage.getItem(LEFTOVER_KEY)).toBeNull();
  });

  it('keeps every read running at once revocable after a reload (SAFE-R5-S2)', async () => {
    // My trips closed and opened again while a read runs: a second read starts. Each keeps and
    // drops only its own token, so a reload during the second still revokes it next load.
    const tokens = ['first-token', 'second-token'];
    const revoked: string[] = [];
    let next = 0;
    (window as { google?: unknown }).google = {
      accounts: {
        oauth2: {
          initTokenClient(config: { callback: (answer: { access_token: string }) => void }) {
            return {
              requestAccessToken: () => {
                config.callback({ access_token: tokens[next++] ?? 'more' });
              },
            };
          },
          revoke(token: string) {
            revoked.push(token);
          },
        },
      },
    };
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    let secondStarted: () => void = () => undefined;
    const started = new Promise<void>((resolve) => {
      secondStarted = resolve;
    });
    const first = readGmail('5678-demo.apps.googleusercontent.com', new Map(), async () => {
      await held;
      return new Response(JSON.stringify({ messages: [] }), { status: 200 });
    });
    let secondDone: () => void = () => undefined;
    const end = new Promise<void>((resolve) => {
      secondDone = resolve;
    });
    const second = readGmail('5678-demo.apps.googleusercontent.com', new Map(), async () => {
      secondStarted();
      await end;
      return new Response(JSON.stringify({ messages: [] }), { status: 200 });
    });
    await started;
    expect(JSON.parse(window.sessionStorage.getItem(LEFTOVER_KEY) ?? '[]')).toEqual(tokens);
    // Neither is a leftover while it runs.
    const posted: string[] = [];
    const poster: typeof fetch = (_u, init) => {
      posted.push(typeof init?.body === 'string' ? init.body : '');
      return Promise.resolve(new Response('', { status: 200 }));
    };
    expect(await revokeLeftover(poster)).toBe(false);
    // The first ends: only its own token goes.
    release();
    await first;
    expect(revoked).toEqual(['first-token']);
    expect(JSON.parse(window.sessionStorage.getItem(LEFTOVER_KEY) ?? '[]')).toEqual([
      'second-token',
    ]);
    // A reload now (the page's running list is gone) would revoke the second's token.
    const kept = window.sessionStorage.getItem(LEFTOVER_KEY);
    secondDone();
    await second;
    expect(window.sessionStorage.getItem(LEFTOVER_KEY)).toBeNull();
    window.sessionStorage.setItem(LEFTOVER_KEY, kept ?? '');
    expect(await revokeLeftover(poster)).toBe(true);
    expect(posted).toEqual(['token=second-token']);
    expect(window.sessionStorage.getItem(LEFTOVER_KEY)).toBeNull();
    // A plain token an older page kept is still revoked.
    window.sessionStorage.setItem(LEFTOVER_KEY, 'old-token');
    expect(await revokeLeftover(poster)).toBe(true);
    expect(posted.at(-1)).toBe('token=old-token');
  });
});
