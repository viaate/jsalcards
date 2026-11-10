import assert from 'node:assert/strict';
import { test } from 'node:test';
import { RETRY_WAIT_MS, USER_AGENT, probe } from '../prober/src/probe.ts';
import { PARTS } from '../shared/types.ts';
import {
  CLOSINGS_URL,
  Net,
  STAMP_URL,
  WHERE,
  closingsBody,
  healthy,
  stampBody,
} from './harness.ts';

test('the second try stands', async () => {
  // Slow, then fast: working.
  let net = new Net().on(WHERE.SITE_URL, { status: 200, ms: 3500 }, { status: 200, ms: 200 });
  assert.deepEqual(await probe('site', WHERE, net), {
    s: 'ok',
    code: 200,
    ms: 200,
    made: null,
    allow: 0,
    bytes: null,
  });
  assert.deepEqual(net.waits, [RETRY_WAIT_MS]);
  assert.equal(net.calls.length, 2);
  // An error, then a good answer: working.
  net = new Net().on(
    WHERE.ACCOUNTS_HEALTH_URL,
    { status: 500, body: 'oops' },
    { status: 200, body: '{"ok":true}' },
  );
  assert.equal((await probe('accounts', WHERE, net)).s, 'ok');
  // Slow, then nothing: the check failed, and the slow answer does not stand.
  net = new Net().on(WHERE.SITE_URL, { status: 200, ms: 3500 }, 'none');
  assert.deepEqual(await probe('site', WHERE, net), {
    s: 'unknown',
    code: 0,
    ms: null,
    made: null,
    allow: 0,
    bytes: null,
  });
  // Slow twice: slow.
  net = new Net().on(WHERE.SITE_URL, { status: 200, ms: 3500 });
  assert.deepEqual([(await probe('site', WHERE, net)).s, net.calls.length], ['late', 2]);
  // A file: a 5xx earns a second try, a plain 404 does not.
  net = new Net();
  net.on(CLOSINGS_URL, { status: 503 }, { status: 200, body: closingsBody(net.clock, 60) });
  assert.equal((await probe('closings', WHERE, net)).s, 'ok');
  net = new Net().on(CLOSINGS_URL, { status: 404, body: 'gone' });
  assert.deepEqual([(await probe('closings', WHERE, net)).s, net.calls.length], ['down', 1]);
  net = new Net().on(STAMP_URL, { status: 404, body: 'gone' });
  assert.deepEqual([(await probe('chances', WHERE, net)).s, net.calls.length], ['unknown', 1]);
});

test('one request when all is well', async () => {
  const net = healthy(new Net());
  for (const part of PARTS) assert.equal((await probe(part, WHERE, net)).s, 'ok', part);
  assert.equal(net.calls.length, 4);
  assert.deepEqual(net.waits, []);
});

test('a timeout, or no answer at all, is a failed check', async () => {
  for (const part of PARTS) {
    for (const step of ['timeout', 'none'] as const) {
      const net = new Net()
        .on(WHERE.SITE_URL, step)
        .on(WHERE.ACCOUNTS_HEALTH_URL, step)
        .on(CLOSINGS_URL, step)
        .on(STAMP_URL, step);
      const reading = await probe(part, WHERE, net);
      assert.deepEqual(
        [reading.s, reading.code, reading.ms],
        ['unknown', 0, null],
        `${part} ${step}`,
      );
      assert.equal(net.calls.length, 2);
    }
  }
});

test('the website is a HEAD whose body is never read', async () => {
  const net = new Net().on(WHERE.SITE_URL, { status: 200, body: '<html>the page</html>' });
  assert.equal((await probe('site', WHERE, net)).s, 'ok');
  assert.equal(net.calls[0]!.init.method, 'HEAD');
  assert.equal(net.read.get(WHERE.SITE_URL) ?? 0, 0);
  // Not even of an error page.
  const down = new Net().on(WHERE.SITE_URL, { status: 500, body: 'x'.repeat(100000) });
  assert.equal((await probe('site', WHERE, down)).s, 'down');
  assert.equal(down.read.get(WHERE.SITE_URL) ?? 0, 0);
});

test('every request is asked the same careful way', async () => {
  const net = healthy(new Net());
  for (const part of PARTS) await probe(part, WHERE, net);
  assert.deepEqual(
    net.calls.map((call) => `${call.init.method} ${call.url}`),
    [
      'HEAD https://site.test/',
      'GET https://live.test/v1/live/closings.json',
      'GET https://live.test/v1/predictions/stamp.json',
      'GET https://accounts.test/v1/health',
    ],
  );
  for (const call of net.calls) {
    assert.equal(call.init.cache, 'no-store');
    assert.equal(call.init.redirect, 'follow');
    assert.deepEqual(call.init.headers, { 'User-Agent': USER_AGENT });
    assert.equal(call.init.signal instanceof AbortSignal, true);
  }
  assert.equal(USER_AGENT, 'snowlight-status/1 (+https://status.snowlightmap.com)');
  // A live root given without its last slash reads the same files.
  const bare = healthy(new Net());
  bare.on(CLOSINGS_URL, { status: 200, body: closingsBody(bare.clock, 60) });
  assert.equal(
    (await probe('closings', { ...WHERE, LIVE_ROOT: 'https://live.test/v1' }, bare)).s,
    'ok',
  );
});

test('8 requests a tick at most, and never the chances file itself', async () => {
  const net = new Net()
    .on(WHERE.SITE_URL, { status: 503 })
    .on(WHERE.ACCOUNTS_HEALTH_URL, { status: 503 })
    .on(CLOSINGS_URL, { status: 503 })
    .on(STAMP_URL, { status: 503 });
  const states = await Promise.all(PARTS.map((part) => probe(part, WHERE, net)));
  assert.deepEqual(
    states.map((reading) => reading.s),
    ['down', 'down', 'down', 'down'],
  );
  assert.equal(net.calls.length, 8);
  assert.equal(
    net.calls.some((call) => call.url.includes('predictions/latest.json')),
    false,
  );
});

test('of a body only a stamp and a length are kept', async () => {
  // A large closings file: its length is counted and only its end is held.
  const net = new Net();
  const end = closingsBody(net.clock, 120).slice(1);
  const big = new Uint8Array(1_000_000).fill(0x20);
  big[0] = 0x7b;
  big.set(new TextEncoder().encode(end), big.length - end.length);
  net.on(CLOSINGS_URL, { status: 200, body: big, headers: { Age: '30' } });
  assert.deepEqual(await probe('closings', WHERE, net), {
    s: 'ok',
    code: 200,
    ms: 100,
    made: Math.floor(net.clock / 1000) - 120,
    allow: 30,
    bytes: 1_000_000,
  });
  // A small one is read whole.
  const small = new Net();
  const body = closingsBody(small.clock, 30);
  small.on(CLOSINGS_URL, { status: 200, body });
  assert.equal((await probe('closings', WHERE, small)).bytes, body.length);
  // The stamp: a body that is too long is not read to its end.
  const long = new Net().on(STAMP_URL, { status: 200, body: 'x'.repeat(500000) });
  const reading = await probe('chances', WHERE, long);
  assert.deepEqual([reading.s, reading.bytes], ['unknown', null]);
  assert.equal((long.read.get(STAMP_URL) ?? 0) <= 2, true);
  // Accounts: a long answer is not read to its end either, and is not a health answer.
  const chatty = new Net().on(WHERE.ACCOUNTS_HEALTH_URL, {
    status: 200,
    body: `{"ok":true,"p":"${'x'.repeat(500000)}"}`,
  });
  assert.equal((await probe('accounts', WHERE, chatty)).s, 'down');
  assert.equal((chatty.read.get(WHERE.ACCOUNTS_HEALTH_URL) ?? 0) <= 2, true);
  const refused = new Net().on(WHERE.ACCOUNTS_HEALTH_URL, {
    status: 404,
    body: 'error code: 1042',
  });
  assert.equal((await probe('accounts', WHERE, refused)).s, 'unknown');
  const fresh = new Net();
  fresh.on(STAMP_URL, { status: 200, body: stampBody(fresh.clock, 2701), headers: { age: '1' } });
  assert.deepEqual(await probe('chances', WHERE, fresh), {
    s: 'ok',
    code: 200,
    ms: 100,
    made: Math.floor(fresh.clock / 1000) - 2701,
    allow: 1,
    bytes: null,
  });
});
