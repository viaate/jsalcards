import { describe, expect, it } from 'vitest';

import { apiRoot, asksForAdmin } from '../config';

describe('apiRoot', () => {
  it('takes an https root and drops its trailing slash', () => {
    expect(apiRoot('https://snowlight-api.example.workers.dev/', false)).toBe(
      'https://snowlight-api.example.workers.dev',
    );
  });

  it('is null when unset, empty or not https', () => {
    expect(apiRoot(undefined, false)).toBeNull();
    expect(apiRoot('', false)).toBeNull();
    expect(apiRoot('  ', false)).toBeNull();
    expect(apiRoot('http://api.example.com', false)).toBeNull();
    expect(apiRoot('not a url', false)).toBeNull();
    expect(apiRoot('https://api.example.com/?x=1', false)).toBeNull();
  });

  it('allows plain http on this machine only for a local test build', () => {
    expect(apiRoot('http://127.0.0.1:8787', false)).toBeNull();
    expect(apiRoot('http://127.0.0.1:8787', true)).toBe('http://127.0.0.1:8787');
    expect(apiRoot('http://example.com', true)).toBeNull();
  });

  it('reads ?admin', () => {
    expect(asksForAdmin('?admin')).toBe(true);
    expect(asksForAdmin('?school=1&admin=1')).toBe(true);
    expect(asksForAdmin('?school=1')).toBe(false);
  });
});
