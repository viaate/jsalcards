/**
 * The formatters (copy-format.ts) load after the page's first script, once
 * the page has painted. The update time, the menu and the school panel word
 * with them, and their code imports them: it is asked for only once this has
 * settled. A browser keeps a module that failed to download as failed, with
 * every module that imports it, for as long as the page is open; so the file
 * is fetched first, and again after a failed or stalled download (app/tries.ts),
 * and imported only once a fetch has brought it into the browser's cache.
 */

import FORMATS_URL from 'virtual:snowlight/copy-format-url';

import { tries } from './tries';

export interface LateFormatsOptions {
  /** The first try waits for this: the page's first paint. */
  readonly after?: Promise<unknown>;
  readonly signal?: AbortSignal;
  /** The file, at a try counted from 0; by default the build's chunk, fetched. */
  readonly download?: (attempt: number) => Promise<unknown>;
  /** By default the build's chunk, imported. */
  readonly load?: () => Promise<unknown>;
}

/** A later try goes past a stalled one: the browser holds a request for the same file behind it. */
function download(attempt: number): Promise<ArrayBuffer> {
  return fetch(FORMATS_URL, attempt === 0 ? {} : { cache: 'reload' }).then((response) =>
    response.arrayBuffer(),
  );
}

/**
 * Settles once the formatters have run, or could not: a server's answer
 * other than the file ends the tries, and the code that imports them then
 * fails to load as any other would.
 */
export function lateFormats(options: LateFormatsOptions = {}): Promise<void> {
  const {
    after = Promise.resolve(),
    signal,
    download: get = download,
    load = () => import(/* @vite-ignore */ FORMATS_URL),
  } = options;
  return after
    .then(() => {
      const attempts = tries(get);
      signal?.addEventListener('abort', attempts.stop);
      return attempts.won;
    })
    .then(load)
    .then(
      () => undefined,
      () => undefined,
    );
}
