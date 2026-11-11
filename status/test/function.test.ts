import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { onRequest, onRequestGet } from '../page/functions/api/status.ts';
import { tick } from '../prober/src/tick.ts';
import { Net, WHERE, healthy, startStore } from './harness.ts';
import type { Store } from './harness.ts';

let store: Store;
before(async () => {
  store = await startStore();
});
after(async () => {
  await store.close();
});

type Context = Parameters<typeof onRequestGet>[0];
const call = (handler: typeof onRequestGet, db: unknown): Promise<Response> =>
  Promise.resolve(handler({ env: { DB: db } } as unknown as Context)) as Promise<Response>;

test('before the first tick the summary is null', async () => {
  const before = Math.floor(Date.now() / 1000);
  const response = await call(onRequestGet, store.db);
  assert.equal(response.status, 200);
  const body = (await response.json()) as { served: number; summary: unknown };
  assert.deepEqual(Object.keys(body), ['served', 'summary']);
  assert.equal(body.summary, null);
  assert.equal(body.served >= before && body.served <= before + 5, true);
});

test('the summary as the checker wrote it, with the headers and no cookie', async () => {
  const t = 1_800_000_300;
  await tick({ ...WHERE, DB: store.db }, t, healthy(new Net(t * 1000 + 2000)));
  const response = await call(onRequestGet, store.db);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('content-type'), 'application/json; charset=utf-8');
  // Never kept: a reload answered from the browser's cache would set the page's clock back.
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
  assert.equal(response.headers.get('set-cookie'), null);
  assert.deepEqual([...response.headers.keys()].sort(), [
    'cache-control',
    'content-type',
    'x-content-type-options',
  ]);
  const text = await response.text();
  const row = (await store.sql<{ v: string }>("SELECT v FROM meta WHERE k = 'summary'"))[0]!.v;
  assert.match(text, /^\{"served":\d+,"summary":\{"v":1,/);
  assert.equal(
    text,
    `{"served":${(JSON.parse(text) as { served: number }).served},"summary":${row}}`,
  );
  assert.equal((JSON.parse(text) as { summary: { now: number } }).summary.now, t);
});

test('a store that fails is a 503 that is not cached', async () => {
  for (const broken of [
    {
      prepare() {
        throw new Error('D1 is down');
      },
    },
    { prepare: () => ({ first: () => Promise.reject(new Error('D1 is down')) }) },
  ]) {
    const response = await call(onRequestGet, broken);
    assert.equal(response.status, 503);
    assert.equal(await response.text(), '{"error":"store"}');
    assert.equal(response.headers.get('cache-control'), 'no-store');
    assert.equal(response.headers.get('set-cookie'), null);
  }
});

test('every other method is refused', async () => {
  // Pages calls onRequest for a method with no handler of its own: POST, HEAD and the rest.
  const response = await call(onRequest, store.db);
  assert.equal(response.status, 405);
  assert.equal(response.headers.get('allow'), 'GET');
  assert.equal(await response.text(), '');
  const exported = await import('../page/functions/api/status.ts');
  assert.deepEqual(Object.keys(exported).sort(), ['onRequest', 'onRequestGet']);
});
