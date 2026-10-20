import type { Plugin } from 'vite';

import { checkApiRoot } from '../src/account/root.ts';

/**
 * Marks the page as one with account controls: `data-accounts` on <html>
 * when the build names an accounts API (VITE_API_ROOT), so index.html keeps
 * the account control's room in the top strip from the first paint
 * (--account-room) and nothing moves when it appears. A root set to anything
 * account/config.ts refuses fails the build rather than turning accounts off
 * without a word.
 */
export function accounts(env: Readonly<Record<string, string | undefined>>): Plugin {
  const raw = env.VITE_API_ROOT ?? '';
  const root = checkApiRoot(raw, env.VITE_API_LOOPBACK === '1');
  if (raw.trim() !== '' && root === null) {
    throw new Error(
      `VITE_API_ROOT must be an https URL with no query, fragment or credentials; got ${JSON.stringify(raw)}`,
    );
  }
  return {
    name: 'snowlight:accounts',
    transformIndexHtml: {
      order: 'pre',
      handler: (html) => {
        if (root === null) return html;
        if (!html.includes('<html lang="en">'))
          throw new Error('accounts: no <html lang="en"> tag');
        return html.replace('<html lang="en">', '<html lang="en" data-accounts>');
      },
    },
  };
}
