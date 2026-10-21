import { webcrypto } from 'node:crypto';
import { describe, expect, it } from 'vitest';

import {
  deriveKey,
  deriveWithSalt,
  loginSalt,
  normalizeLogin,
  passwordProblem,
  randomSalt,
  temporaryPassword,
} from '../key';

describe('deriveKey', () => {
  // The same vector is in api/test/derive-key.test.ts: the deploy runner derives the admin's
  // key the way this page does, so the two must agree exactly.
  it('matches the runner’s key for the same login and password', async () => {
    const key = await deriveKey(
      ' Test@Example.com',
      'correct horse battery',
      webcrypto.subtle as SubtleCrypto,
    );
    expect(key).toBe('67B2DvpiHPqn1Z_iJPni-jyc5JcCMMB-PjBHI8n9-A0');
  });

  it('gives another key for another login with the same password', async () => {
    const subtle = webcrypto.subtle as SubtleCrypto;
    const a = await deriveKey('a@example.com', 'correct horse battery', subtle);
    const b = await deriveKey('b@example.com', 'correct horse battery', subtle);
    expect(a).not.toBe(b);
    expect(a).toMatch(/^[A-Za-z0-9_-]{43}$/);
  });
});

describe('deriveWithSalt', () => {
  it('derives a v1 key from the salt the Worker hands back for it', async () => {
    const subtle = webcrypto.subtle as SubtleCrypto;
    const salt = await loginSalt(' Test@Example.com', subtle);
    expect(await deriveWithSalt(salt, 'correct horse battery', subtle)).toBe(
      '67B2DvpiHPqn1Z_iJPni-jyc5JcCMMB-PjBHI8n9-A0',
    );
  });

  it('makes fresh 16-byte salts that give different keys', async () => {
    const subtle = webcrypto.subtle as SubtleCrypto;
    const a = randomSalt();
    const b = randomSalt();
    expect(a).toMatch(/^[A-Za-z0-9_-]{22}$/);
    expect(a).not.toBe(b);
    expect(await deriveWithSalt(a, 'pw', subtle)).not.toBe(await deriveWithSalt(b, 'pw', subtle));
  });
});

describe('passwords', () => {
  it('normalizes logins', () => {
    expect(normalizeLogin('  OLIVIA ')).toBe('olivia');
  });

  it('refuses short, long and common passwords', () => {
    expect(passwordProblem('short')).toBe('password_short');
    expect(passwordProblem('x'.repeat(129))).toBe('password_long');
    expect(passwordProblem('Password123')).toBe('password_common');
    expect(passwordProblem('snow day on tuesday')).toBeNull();
    // Characters, not bytes: eight letters with accents are eight.
    expect(passwordProblem('éééééééé')).toBeNull();
  });

  it('makes temporary passwords that pass the rules', () => {
    const made = new Set<string>();
    for (let i = 0; i < 50; i++) {
      const password = temporaryPassword();
      expect(password).toMatch(/^[a-km-np-zA-HJ-NP-Z2-9]{16}$/);
      expect(passwordProblem(password)).toBeNull();
      made.add(password);
    }
    expect(made.size).toBe(50);
  });
});
