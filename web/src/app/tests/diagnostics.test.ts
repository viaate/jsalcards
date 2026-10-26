import { describe, expect, it } from 'vitest';

import { diagCopy, diagFormat } from '../../copy-diag';
import { asksForDiagnostics } from '../diagnostics';

describe('asksForDiagnostics', () => {
  it('reads ?diag=1 and nothing else', () => {
    expect(asksForDiagnostics('?diag=1')).toBe(true);
    expect(asksForDiagnostics('?school=1&diag=1')).toBe(true);
    expect(asksForDiagnostics('?diag=0')).toBe(false);
    expect(asksForDiagnostics('?diag')).toBe(false);
    expect(asksForDiagnostics('?school=1')).toBe(false);
    expect(asksForDiagnostics('')).toBe(false);
  });
});

describe('the screen check’s words', () => {
  it('writes sizes, zoom, shift, widths and safe areas plainly', () => {
    expect(diagFormat.size(951, 543)).toBe('951 × 543');
    expect(diagFormat.size(891.5625, 509.0625)).toBe('891.56 × 509.06');
    expect(diagFormat.number(16 / 15)).toBe('1.07');
    expect(diagFormat.number(Number.NaN)).toBe('–');
    expect(diagFormat.pair(59.4375, 0)).toBe('59.44, 0');
    expect(diagFormat.over(951, 951)).toBe('951 / 951');
    expect(diagFormat.sides(0, 59, 21, 59)).toBe('0 · 59 · 21 · 59');
  });

  it('is frozen', () => {
    expect(Object.isFrozen(diagCopy)).toBe(true);
    expect(Object.isFrozen(diagFormat)).toBe(true);
  });
});
