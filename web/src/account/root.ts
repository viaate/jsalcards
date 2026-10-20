/**
 * An accounts API root, checked: https (or plain http on this machine for a
 * local test build), with no query, fragment or credentials, without its
 * trailing slash; null otherwise. Shared by the page (config.ts) and the build
 * (tools/accounts.ts), so both read a root the same way.
 */
export function checkApiRoot(raw: string | undefined, loopback: boolean): string | null {
  if (typeof raw !== 'string' || raw.trim() === '') return null;
  let url: URL;
  try {
    url = new URL(raw.trim());
  } catch {
    return null;
  }
  const local = url.hostname === 'localhost' || url.hostname === '127.0.0.1';
  if (url.protocol !== 'https:' && !(loopback && local && url.protocol === 'http:')) return null;
  if (url.search !== '' || url.hash !== '' || url.username !== '' || url.password !== '')
    return null;
  return url.href.replace(/\/+$/, '');
}
