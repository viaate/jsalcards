import assert from 'node:assert/strict';
import { test } from 'node:test';
import { STAMP_MAX_BYTES, TAIL_BYTES, instant, readStamp } from '../shared/stamp.ts';

const text = (s: string): Uint8Array => new TextEncoder().encode(s);
const MADE = Date.UTC(2026, 10, 10, 13, 37, 0) / 1000;

test('an instant has one form', () => {
  assert.equal(instant('2026-11-10T13:37:00Z'), MADE);
  for (const other of [
    '2026-11-10T13:37:00+00:00',
    '2026-11-10T13:37:00.000Z',
    '2026-11-10 13:37:00Z',
    '2026-11-10T13:37Z',
    '2026-02-30T00:00:00Z',
    '2026-11-10T25:00:00Z',
    '',
    7,
    null,
  ]) {
    assert.equal(instant(other), null, String(other));
  }
});

test('a small closings file is parsed whole', () => {
  const file = text('{"closings":[],"generated_at":"2026-11-10T13:37:00Z","schema_version":1}');
  assert.deepEqual(readStamp('closings', file), { made: MADE, bad: false, blank: false });
  // The top-level stamp only: one inside a closing is not the file's.
  const inner = text('{"closings":[{"generated_at":"2026-11-10T13:37:00Z"}],"schema_version":1}');
  assert.deepEqual(readStamp('closings', inner), { made: null, bad: true, blank: false });
  for (const broken of ['', '{', '[]', 'null', '{"generated_at":"yesterday"}', '<html></html>']) {
    assert.deepEqual(
      readStamp('closings', text(broken)),
      { made: null, bad: true, blank: false },
      broken,
    );
  }
});

test('a large closings file gives its stamp from its last bytes', () => {
  const end = '"generated_at":"2026-11-10T13:37:00Z","schema_version":1}';
  // The head is not JSON at all: a stamp found shows that only the tail was read.
  const big = new Uint8Array(3_000_000).fill(0x5b);
  big.set(text(end), big.length - end.length);
  assert.deepEqual(readStamp('closings', big), { made: MADE, bad: false, blank: false });
  // The last of several is the file's own.
  const twice = new Uint8Array(TAIL_BYTES + 1).fill(0x20);
  twice.set(text('"generated_at":"2020-01-01T00:00:00Z",'), 100);
  twice.set(text(end), twice.length - end.length);
  assert.equal(readStamp('closings', twice).made, MADE);
  // No stamp in the last 65,536 bytes: the checker's own limit, never the file's fault.
  const far = new Uint8Array(3_000_000).fill(0x5b);
  far.set(text(end), far.length - TAIL_BYTES - end.length);
  assert.deepEqual(readStamp('closings', far), { made: null, bad: false, blank: false });
  const odd = new Uint8Array(TAIL_BYTES + 1).fill(0x5b);
  odd.set(text('"generated_at":"not an instant....."}'), odd.length - 40);
  assert.deepEqual(readStamp('closings', odd), { made: null, bad: false, blank: false });
});

test('the chances stamp', () => {
  const written = '{"districts":13000,"generated_at":"2026-11-10T13:37:00Z","schema_version":1}\n';
  assert.deepEqual(readStamp('chances', text(written)), { made: MADE, bad: false, blank: false });
  const blank = '{"districts":0,"generated_at":"2026-11-10T13:37:00Z","schema_version":1}\n';
  assert.deepEqual(readStamp('chances', text(blank)), { made: MADE, bad: false, blank: true });
  const none = { made: null, bad: false, blank: false };
  const padded = `{"districts":1,"generated_at":"2026-11-10T13:37:00Z","pad":"${'x'.repeat(1024)}"}`;
  assert.equal(text(padded).length > STAMP_MAX_BYTES, true);
  assert.deepEqual(readStamp('chances', text(padded)), none);
  assert.deepEqual(readStamp('chances', text(written.padEnd(1025, ' '))), none);
  assert.equal(readStamp('chances', text(written.padEnd(1024, ' '))).made, MADE);
  for (const wrong of [
    '{"districts":13000,"generated_at":"2026-11-10 13:37","schema_version":1}',
    '{"generated_at":"2026-11-10T13:37:00Z","schema_version":1}',
    '{"districts":-1,"generated_at":"2026-11-10T13:37:00Z"}',
    '{"districts":"13000","generated_at":"2026-11-10T13:37:00Z"}',
    '{"districts":1.5,"generated_at":"2026-11-10T13:37:00Z"}',
    '[]',
    'null',
    '<html>',
    '',
  ]) {
    assert.deepEqual(readStamp('chances', text(wrong)), none, wrong);
  }
});
