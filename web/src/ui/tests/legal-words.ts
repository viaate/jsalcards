/**
 * The owner's approved privacy policy and terms of use, as words, for the word-for-word checks of
 * the pages (ui/tests/legal-page.test.ts, e2e/legal.spec.ts).
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import type { LegalPageName } from '../../copy-legal';

/**
 * The owner's approved text (rev 14, Nov 9, 2026), as the lead's spec gives it: both pages in one
 * Markdown file, the privacy policy first.
 */
export const APPROVED = readFileSync(
  path.join(path.dirname(fileURLToPath(import.meta.url)), 'legal-approved.txt'),
  'utf8',
);

/**
 * Words as a person reads them, for a word-for-word comparison: the site's curly apostrophe read
 * as the draft's straight one, and every run of spaces and line breaks one space.
 */
export function words(text: string): string {
  return text.replaceAll('’', "'").replace(/\s+/gu, ' ').trim();
}

/** The approved Markdown of one page, as words: its headings, paragraphs, list items and table cells. */
export function approvedWords(page: LegalPageName): string {
  const split = APPROVED.indexOf('\n# Terms of use\n');
  const markdown = page === 'privacy' ? APPROVED.slice(0, split) : APPROVED.slice(split);
  const lines = markdown
    .split('\n')
    .filter((line) => line.trim() !== '' && !/^\|(?:\s*-+\s*\|)+$/u.test(line.trim()))
    .map((line) =>
      line.startsWith('|')
        ? line.split('|').join(' ')
        : line.replace(/^#+\s+/u, '').replace(/^-\s+/u, ''),
    )
    .map((line) => line.replaceAll('**', ''));
  return words(lines.join(' '));
}
