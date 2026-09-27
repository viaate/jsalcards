/**
 * The names data files are published under.
 *
 * Files that change only with a new directory or index build (the school
 * directory, the school tiles, the search index) are published with a hash
 * of their content in the name, "schools/meta.0123456789.json", so a browser
 * or the service worker can keep a copy as long as it likes: new content
 * comes under a new name (scripts/stage-data.mjs names them). The page asks
 * for every file by its plain name, "schools/meta.json", and the build's
 * list of files (tools/data-files.ts) says what that name is published as.
 * Files that change during the day keep their plain names.
 *
 * This module has no imports, so Node can load it directly from the scripts.
 */

/** Hex digits of the content hash in a published name. */
export const HASH_LENGTH = 10;

const HASHED = new RegExp(`^((?:.*/)?[^/]+)\\.[0-9a-f]{${String(HASH_LENGTH)}}(\\.[^./]+)$`);

/** The plain name a published file is asked for by: its name without a content hash. */
export function plainPath(published: string): string {
  const match = HASHED.exec(published);
  return match === null ? published : `${match[1] ?? ''}${match[2] ?? ''}`;
}

/** `path` published with `hash` (hex, at least HASH_LENGTH digits) in its name. */
export function hashedPath(path: string, hash: string): string {
  const cut = path.lastIndexOf('.');
  if (cut <= path.lastIndexOf('/') + 1) throw new Error(`${path}: no extension to hash before`);
  const digits = hash.slice(0, HASH_LENGTH);
  if (!new RegExp(`^[0-9a-f]{${String(HASH_LENGTH)}}$`).test(digits)) {
    throw new Error(`${hash}: not a hex hash`);
  }
  return `${path.slice(0, cut)}.${digits}${path.slice(cut)}`;
}
