/**
 * The check that schools/edition.json names the directory staged with it, for
 * scripts/stage-data.mjs (and its tests).
 *
 * The edition is the stamp of schools/meta.json (its date and counts) and
 * content_sha256: the SHA-256 of meta.json's bytes with the text of its date
 * emptied, followed by points.bin's bytes
 * (pipeline/snowlight/schemas/directory.py written_digest). The live ingest
 * reads the deployed edition to prove its indexes point into the directory the
 * site serves, so an edition that names another directory would let it light
 * the wrong schools: staging refuses one.
 */

import { createHash } from 'node:crypto';

/** What a staging error says, without a stack. */
export class EditionError extends Error {}

export const EDITION = 'schools/edition.json';
const META = 'schools/meta.json';
/** The edition's keys, as the pipeline's model has them; no other key is allowed. */
const KEYS = ['content_sha256', 'districts', 'generated_on', 'schema_version', 'schools'];

/** @param {Uint8Array} bytes */
function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

/**
 * Throws unless `bytes` is the edition of the directory in `metaBytes` and
 * `pointsBytes`: schema version 1, only the model's keys, the stamp of `meta`,
 * and its content digest.
 * @param {Uint8Array} bytes edition.json
 * @param {Uint8Array} metaBytes meta.json, as written
 * @param {Uint8Array} pointsBytes points.bin
 * @param {{ generated_on: string, count: number, districts: { ids: unknown[] } }} meta
 */
export function checkEdition(bytes, metaBytes, pointsBytes, meta) {
  /** @type {unknown} */
  let parsed;
  try {
    parsed = JSON.parse(Buffer.from(bytes).toString('utf8'));
  } catch {
    throw new EditionError(`${EDITION} is not JSON`);
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new EditionError(`${EDITION} is not an object`);
  }
  const edition = /** @type {Record<string, unknown>} */ (parsed);
  const keys = Object.keys(edition).sort();
  if (keys.join() !== KEYS.join()) {
    throw new EditionError(`${EDITION} has the keys ${keys.join(', ')}, not ${KEYS.join(', ')}`);
  }
  const metaText = Buffer.from(metaBytes);
  const dated = Buffer.from(`"generated_on":${JSON.stringify(meta.generated_on)}`);
  const at = metaText.indexOf(dated);
  if (at < 0 || metaText.indexOf(dated, at + 1) >= 0) {
    throw new EditionError(`${META}: its date is not written once as the pipeline writes it`);
  }
  const blanked = Buffer.concat([
    metaText.subarray(0, at),
    Buffer.from('"generated_on":""'),
    metaText.subarray(at + dated.length),
    Buffer.from(pointsBytes),
  ]);
  if (
    edition.schema_version !== 1 ||
    edition.generated_on !== meta.generated_on ||
    edition.schools !== meta.count ||
    edition.districts !== meta.districts.ids.length ||
    edition.content_sha256 !== sha256(blanked)
  ) {
    throw new EditionError(`${EDITION} does not name the ${META} and points.bin beside it`);
  }
}

/**
 * Throws when the directory build recorded writing edition.json but it is not
 * there: staging without it would ship a site the live ingest cannot check.
 * A build older than editions records none, and its staging only says so.
 * @param {{ outputs?: Record<string, unknown> } | null} manifest the build's record, if kept
 * @param {boolean} present whether edition.json is beside meta.json
 */
export function checkEditionPresent(manifest, present) {
  if (!present && manifest?.outputs?.['edition.json'] !== undefined) {
    throw new EditionError(
      `${EDITION} is missing, but the directory build that wrote ${META} wrote one`,
    );
  }
}
