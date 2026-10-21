import { describe, expect, it } from 'vitest';

import { MAX_ADMIN_TERMS } from '../../../../api/src/usernames/check';
import { adminCopy } from '../../copy-account';
import { MAX_TERMS } from '../call';

describe('the moderation word limit', () => {
  it('is the Worker limit, and the message names it', () => {
    expect(MAX_TERMS).toBe(MAX_ADMIN_TERMS);
    expect(adminCopy.moderation.full).toContain(String(MAX_TERMS));
  });
});
