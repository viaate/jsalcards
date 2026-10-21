import { describe, expect, it } from 'vitest';

import { accountFormat } from '../../copy-account';

describe('a network with many sign-ups, in the admin overview', () => {
  it('names the network, the count and the day', () => {
    expect(accountFormat.busyNetwork('203.0.113.0/24', 7, '2026-10-20')).toBe(
      '203.0.113.0/24: 7 sign-ups on Tue, Oct 20',
    );
    expect(accountFormat.busyNetwork('2001:db8:1:2::/64', 1200, '2026-10-21')).toBe(
      '2001:db8:1:2::/64: 1,200 sign-ups on Wed, Oct 21',
    );
  });
});
