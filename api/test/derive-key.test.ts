import assert from 'node:assert/strict';
import { it } from 'node:test';
// @ts-expect-error: a plain .mjs script without types.
import { deriveKey } from '../scripts/derive-key.mjs';

// The same vector is in web/src/account/tests/key.test.ts: the runner and the
// browser must derive the same key for the same login and password.
it('derives the key the browser derives', async () => {
  assert.equal(
    await deriveKey(' Test@Example.com', 'correct horse battery'),
    '67B2DvpiHPqn1Z_iJPni-jyc5JcCMMB-PjBHI8n9-A0',
  );
});
