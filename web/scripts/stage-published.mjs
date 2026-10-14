// @ts-check
/**
 * The part of staging (scripts/stage-data.mjs) that takes the pipeline's
 * other published files as they are: live/, predictions/, stats/, the track
 * record and the storm replays. In a module of its own so a test can run it
 * on a folder of its own (tests/stage-published.test.ts).
 *
 * Each replay day is published under a content-hashed name (src/data/paths.ts
 * hashedOnStaging), after a check that it is stamped for the directory staged
 * with it: a day stamped for another directory would never light, so staging
 * stops rather than publish it. replays/index.json keeps its plain name.
 */

import { copyFileSync, mkdirSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';

/**
 * Every file under `root`, as sorted POSIX paths relative to it.
 * @param {string} root @param {string} [prefix]
 * @returns {string[]}
 */
export function filesUnder(root, prefix = '') {
  return readdirSync(join(root, prefix), { withFileTypes: true })
    .flatMap((entry) =>
      entry.isDirectory()
        ? filesUnder(root, `${prefix}${entry.name}/`)
        : entry.isFile()
          ? [`${prefix}${entry.name}`]
          : [],
    )
    .sort();
}

/** Whether a file under site-data is published (tools/data-files.ts isPublished, per name). */
export const published = (/** @type {string} */ path) =>
  path.split('/').every((name) => !name.startsWith('.') && !name.endsWith('.internal.json'));

/**
 * @typedef {{ generated_on: string, schools: number, districts: number }} Stamp
 */

/**
 * Why a replay day's bytes cannot be staged with the directory `stamp`, or
 * null when they can: a file that is not JSON, or is stamped for another
 * directory.
 * @param {string} path @param {Buffer} bytes @param {Stamp} stamp
 * @returns {string | null}
 */
export function replayStampProblem(path, bytes, stamp) {
  /** @type {unknown} */
  let file;
  try {
    file = JSON.parse(bytes.toString('utf8'));
  } catch {
    return `${path}: not JSON`;
  }
  const found =
    typeof file === 'object' && file !== null && 'directory' in file ? file.directory : null;
  const same =
    typeof found === 'object' &&
    found !== null &&
    'generated_on' in found &&
    'schools' in found &&
    'districts' in found &&
    found.generated_on === stamp.generated_on &&
    found.schools === stamp.schools &&
    found.districts === stamp.districts;
  return same
    ? null
    : `${path}: stamped for directory ${JSON.stringify(found)}, not the one staged ` +
        `(${JSON.stringify(stamp)}); publish the replays again against it`;
}

/**
 * Stops with `fail` at the first replay day under `site` not stamped for
 * `stamp`, before anything is written.
 * @param {Pick<StageOthers, 'site' | 'skip' | 'stamp' | 'hashed' | 'fail'>} options
 */
export function checkStamps({ site, skip, stamp, hashed, fail }) {
  for (const path of filesUnder(site)) {
    if (skip(path) || !published(path) || !hashed(path)) continue;
    const problem = replayStampProblem(path, readFileSync(join(site, path)), stamp);
    if (problem !== null) fail(problem);
  }
}

/**
 * @typedef {object} StageOthers
 * @property {string} site the pipeline's site-data folder
 * @property {string} to the folder being staged
 * @property {(path: string) => boolean} skip files staged elsewhere, or not published
 * @property {Stamp} stamp the directory staged
 * @property {(path: string) => boolean} hashed whether a path is staged under a hashed name
 * @property {(path: string, bytes: Buffer) => void} putHashed stages under a hashed name
 * @property {(message: string) => never} fail stops the staging
 */

/**
 * Stages every other published file under `site`, as written, but replay
 * days under hashed names once their stamp is checked. Returns each plain
 * file staged with its size.
 * @param {StageOthers} options
 * @returns {[string, number][]}
 */
export function stageOthers({ site, to, skip, stamp, hashed, putHashed, fail }) {
  checkStamps({ site, skip, stamp, hashed, fail });
  /** @type {[string, number][]} */
  const staged = [];
  for (const path of filesUnder(site)) {
    if (skip(path) || !published(path)) continue;
    if (hashed(path)) {
      putHashed(path, readFileSync(join(site, path)));
      continue;
    }
    mkdirSync(dirname(join(to, path)), { recursive: true });
    copyFileSync(join(site, path), join(to, path));
    staged.push([path, statSync(join(to, path)).size]);
  }
  return staged;
}
