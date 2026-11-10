import assert from 'node:assert/strict';
import { test } from 'node:test';
import { probe } from '../prober/src/probe.ts';
import {
  CHANCES_DOWN,
  CHANCES_LATE,
  CLOSINGS_DOWN,
  CLOSINGS_LATE,
  allowance,
  judgeAccounts,
  judgeFile,
  judgeSite,
  wantsSecondTry,
} from '../shared/judge.ts';
import { Net, WHERE } from './harness.ts';

const NOW = 1_800_000_000;
const text = (s: string): Uint8Array => new TextEncoder().encode(s);
const at = (seconds: number): string =>
  `${new Date((NOW - seconds) * 1000).toISOString().slice(0, 19)}Z`;
const closings = (seconds: number): Uint8Array =>
  text(`{"closings":[],"generated_at":"${at(seconds)}","schema_version":1}`);
const stamp = (seconds: number, districts: unknown = 13000): Uint8Array =>
  text(
    `{"districts":${JSON.stringify(districts)},"generated_at":"${at(seconds)}","schema_version":1}\n`,
  );

test('the website: the status code and the time to it', () => {
  assert.equal(judgeSite({ code: 200, ms: 3000 }), 'ok');
  assert.equal(judgeSite({ code: 200, ms: 3001 }), 'late');
  assert.equal(judgeSite({ code: 404, ms: 10 }), 'down');
  assert.equal(judgeSite({ code: 500, ms: 10 }), 'down');
  assert.equal(judgeSite({ code: 429, ms: 10 }), 'unknown');
  assert.equal(judgeSite(null), 'unknown');
});

test('accounts: a 200 must carry its own small health answer', () => {
  assert.equal(judgeAccounts({ code: 200, ms: 3000 }, '{"ok":true}'), 'ok');
  assert.equal(judgeAccounts({ code: 200, ms: 3001 }, '{"ok":true}'), 'late');
  assert.equal(judgeAccounts({ code: 404, ms: 10 }, 'not found'), 'down');
  assert.equal(judgeAccounts({ code: 500, ms: 10 }, ''), 'down');
  assert.equal(judgeAccounts({ code: 429, ms: 10 }, ''), 'unknown');
  assert.equal(judgeAccounts(null, null), 'unknown');
  for (const wrong of [
    '',
    'ok',
    '[]',
    'null',
    '{"ok":false}',
    '{"ok":"true"}',
    '<html>ok</html>',
  ]) {
    assert.equal(judgeAccounts({ code: 200, ms: 10 }, wrong), 'down', wrong);
  }
  const padded = `{"ok":true,"pad":"${'x'.repeat(1024)}"}`;
  assert.equal(judgeAccounts({ code: 200, ms: 10 }, padded), 'down');
  assert.equal(judgeAccounts({ code: 200, ms: 10 }, `{"ok":true,"p":"${'x'.repeat(1005)}"}`), 'ok');
  assert.equal(judgeAccounts({ code: 200, ms: 10 }, null), 'down');
});

test('accounts: Cloudflare refusing the checker itself is not accounts being down', () => {
  assert.equal(judgeAccounts({ code: 404, ms: 10 }, 'error code: 1042'), 'unknown');
  assert.equal(judgeAccounts({ code: 403, ms: 10 }, '<title>Error 1042</title>'), 'unknown');
  assert.equal(judgeAccounts({ code: 404, ms: 10 }, 'error code: 1016'), 'down');
  // At the daily limit accounts refuse every visitor too.
  assert.equal(judgeAccounts({ code: 429, ms: 10 }, 'error code: 1027'), 'unknown');
  assert.equal(judgeAccounts({ code: 503, ms: 10 }, 'error code: 1027'), 'down');
});

test('accounts: an empty address is not asked', async () => {
  const net = new Net();
  const reading = await probe('accounts', { ...WHERE, ACCOUNTS_HEALTH_URL: '' }, net);
  assert.deepEqual(reading, { s: 'unknown', code: 0, ms: null, made: null, allow: 0, bytes: null });
  assert.equal(net.calls.length, 0);
});

test('a file: each threshold and one second past it', () => {
  const file = (part: 'closings' | 'chances', age: number, header: string | null = null) =>
    judgeFile(part, {
      code: 200,
      age: header,
      body: part === 'closings' ? closings(age) : stamp(age),
      now: NOW,
    }).s;
  assert.equal(file('closings', CLOSINGS_LATE), 'ok');
  assert.equal(file('closings', CLOSINGS_LATE + 1), 'late');
  assert.equal(file('closings', CLOSINGS_DOWN), 'late');
  assert.equal(file('closings', CLOSINGS_DOWN + 1), 'down');
  assert.equal(file('chances', CHANCES_LATE), 'ok');
  assert.equal(file('chances', CHANCES_LATE + 1), 'late');
  assert.equal(file('chances', CHANCES_DOWN), 'late');
  assert.equal(file('chances', CHANCES_DOWN + 1), 'down');
  assert.deepEqual(
    [CLOSINGS_LATE, CLOSINGS_DOWN, CHANCES_LATE, CHANCES_DOWN],
    [900, 3600, 2700, 5400],
  );
  // Past its threshold but inside what the CDN's copy is allowed: working. One second outside: late.
  assert.equal(file('closings', 900 + 600, '600'), 'ok');
  assert.equal(file('closings', 900 + 601, '600'), 'late');
  assert.equal(file('chances', 2700 + 599, '599'), 'ok');
  assert.equal(file('chances', 2700 + 600, '599'), 'late');
  assert.equal(file('chances', 5400 + 600, '4000'), 'late');
  assert.equal(file('chances', 5400 + 601, '4000'), 'down');
  // Ahead of the clock.
  assert.equal(file('closings', -900), 'ok');
  assert.equal(file('closings', -901), 'late');
  assert.equal(file('chances', -901), 'late');
});

test('a file: the allowance is the Age header, 600 at most', () => {
  assert.equal(allowance('0'), 0);
  assert.equal(allowance('599'), 599);
  assert.equal(allowance('600'), 600);
  assert.equal(allowance('601'), 600);
  assert.equal(allowance('999999999'), 600);
  assert.equal(allowance('1234567890'), 0);
  assert.equal(allowance(null), 0);
  assert.equal(allowance('abc'), 0);
  assert.equal(allowance('-5'), 0);
  assert.equal(allowance(' 30'), 0);
  const verdict = judgeFile('closings', { code: 200, age: '45', body: closings(100), now: NOW });
  assert.deepEqual(verdict, { s: 'ok', made: NOW - 100, allow: 45 });
});

test('a file: what does not answer, is not there, or does not read', () => {
  assert.equal(judgeFile('closings', null).s, 'unknown');
  assert.equal(judgeFile('chances', null).s, 'unknown');
  const coded = (part: 'closings' | 'chances', code: number) =>
    judgeFile(part, { code, age: null, body: null, now: NOW }).s;
  assert.equal(coded('closings', 429), 'unknown');
  assert.equal(coded('chances', 429), 'unknown');
  // No stamp on the host says nothing about the chances; no closings file is an outage.
  assert.equal(coded('chances', 404), 'unknown');
  assert.equal(coded('closings', 404), 'down');
  assert.equal(coded('closings', 500), 'down');
  assert.equal(coded('chances', 500), 'down');
  assert.equal(coded('chances', 403), 'down');
  // A stamp that does not read is the checker's trouble; a small closings file that does not
  // parse is the file's.
  const body = (part: 'closings' | 'chances', bytes: Uint8Array) =>
    judgeFile(part, { code: 200, age: null, body: bytes, now: NOW });
  assert.equal(body('chances', text('<html>')).s, 'unknown');
  assert.equal(body('closings', text('<html>')).s, 'down');
  assert.equal(body('closings', text('{"schema_version":1}')).s, 'down');
  assert.deepEqual(body('chances', stamp(60, 0)), { s: 'down', made: NOW - 60, allow: 0 });
  assert.equal(body('chances', stamp(60, 1)).s, 'ok');
  assert.equal(judgeFile('closings', { code: 200, age: null, body: null, now: NOW }).s, 'unknown');
});

test('when a first try earns a second', () => {
  for (const part of ['site', 'accounts'] as const) {
    assert.equal(wantsSecondTry(part, { code: 200, ms: 3000 }), false);
    assert.equal(wantsSecondTry(part, { code: 200, ms: 3001 }), true);
    assert.equal(wantsSecondTry(part, { code: 404, ms: 10 }), true);
    assert.equal(wantsSecondTry(part, null), true);
  }
  for (const part of ['closings', 'chances'] as const) {
    assert.equal(wantsSecondTry(part, { code: 200, ms: 9000 }), false);
    assert.equal(wantsSecondTry(part, { code: 404, ms: 10 }), false);
    assert.equal(wantsSecondTry(part, { code: 429, ms: 10 }), true);
    assert.equal(wantsSecondTry(part, { code: 500, ms: 10 }), true);
    assert.equal(wantsSecondTry(part, { code: 599, ms: 10 }), true);
    assert.equal(wantsSecondTry(part, null), true);
  }
});
