import { describe, expect, it } from 'vitest';

import { adminCopy } from '../../copy-account';
import { renameNoteFor } from '../call';

describe('the note after an admin rename', () => {
  const base = { id: 'u1', username: 'player_0042' } as const;

  it('says the old name is now blocked for everyone', () => {
    expect(
      renameNoteFor({
        ...base,
        blocked: { term: 'meaname', kind: 'substring' },
        block_problem: null,
      }),
    ).toBe(adminCopy.users.renameBlocked);
  });

  it('says why it was not blocked: too short, or the list is full', () => {
    expect(renameNoteFor({ ...base, blocked: null, block_problem: 'too_short' })).toBe(
      adminCopy.users.renameTooShort,
    );
    expect(renameNoteFor({ ...base, blocked: null, block_problem: 'too_many_terms' })).toBe(
      adminCopy.users.renameFull,
    );
  });

  it('says nothing when blocking was not asked for', () => {
    expect(renameNoteFor({ ...base, blocked: null, block_problem: null })).toBeNull();
    expect(renameNoteFor(null)).toBeNull();
  });
});
