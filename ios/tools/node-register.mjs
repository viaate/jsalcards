// node-register.mjs: registers node-hooks.mjs, and hands back what the hooks report.
//
// Import this before importing any of the site's modules. The hooks run on a thread of
// their own, so they report over a message port: every site file they loaded, and which
// site file imported which.
//
// Node's built-in modules only.

import { register } from 'node:module';
import { dirname, join, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { MessageChannel, receiveMessageOnPort } from 'node:worker_threads';

const here = dirname(fileURLToPath(import.meta.url));

/** The repository's root: this file is ios/tools/node-register.mjs. */
export const repoRoot = join(here, '..', '..');
/** web/, ending in a separator. */
export const webRoot = join(repoRoot, 'web') + sep;
/** web/src/, ending in a separator. */
export const siteRoot = join(webRoot, 'src') + sep;

const { port1, port2 } = new MessageChannel();
register('./node-hooks.mjs', {
  parentURL: import.meta.url,
  data: { port: port2, webRoot, siteRoot },
  transferList: [port2],
});
// The port must not keep the process alive once the work is done.
port1.unref();

/**
 * Everything the hooks have reported since the last call. A hook posts its report before
 * it answers Node, so by the time an import has finished its reports are already waiting
 * and can be read without waiting.
 * @returns {Array<{ kind: 'load', path: string } | { kind: 'import', from: string, to: string }>}
 */
export function reported() {
  const messages = [];
  for (;;) {
    const got = receiveMessageOnPort(port1);
    if (got === undefined) break;
    messages.push(got.message);
  }
  return messages;
}
