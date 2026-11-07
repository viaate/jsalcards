/** The admin's Sources tab: the live reader's lit-closing sources (GET /v1/admin/sources), decoded. */

import type { Directory } from '../data/directory';
import { casedName } from '../text/names';

/** One stored day as the API sends it: gzip parts, base64, with the raw JSON's sha256. */
export interface StoredDay {
  readonly day: string;
  readonly sha256: string;
  readonly closings: number;
  readonly published_at: string;
  readonly written_at: string;
  /** The publisher's mode: 'on', or 'shadow' (those statuses are not on the public map). */
  readonly mode: string;
  /** A later publish that did not rewrite these sources (a blank one); null: none. */
  readonly latest_at: string | null;
  readonly parts: readonly string[];
}

/** One lit status's sources: codes, ids and times only. */
export interface SourceRow {
  readonly nces: string;
  readonly status: number | null;
  readonly reason: number | null;
  readonly level: string | null;
  readonly source: string | null;
  readonly type: string | null;
  readonly lo: string | null;
  readonly hi: string | null;
  readonly row_stamp: string | null;
  readonly present: boolean;
  readonly posted_by: string | null;
  readonly contributing: readonly (readonly [string, string])[];
}

export interface SourcesDay {
  readonly day: string;
  readonly publishedAt: string;
  readonly shadow: boolean;
  readonly latestAt: string | null;
  /** null: the parts did not decode, or did not match their sha256. */
  readonly rows: readonly SourceRow[] | null;
  /** With rows null: true when the parts decoded but did not match their sha256 (a write was
   * under way); false when they could not be read at all. */
  readonly writing: boolean;
  readonly links: Readonly<Record<string, string>>;
}

function bytes(base64: string): Uint8Array {
  const text = atob(base64);
  const out = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i += 1) out[i] = text.charCodeAt(i);
  return out;
}

function hex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer), (b) => b.toString(16).padStart(2, '0')).join('');
}

/** A stored day's rows, or null when its parts do not decode to bytes matching its sha256. */
export async function decodeDay(stored: StoredDay): Promise<SourcesDay> {
  const empty = {
    day: stored.day,
    publishedAt: stored.published_at,
    shadow: stored.mode !== 'on',
    latestAt: stored.latest_at ?? null,
    links: {},
    writing: false,
  };
  try {
    if (stored.parts.length === 0) return { ...empty, rows: null };
    const pieces = stored.parts.map(bytes);
    const whole = new Uint8Array(pieces.reduce((n, p) => n + p.length, 0));
    let at = 0;
    for (const piece of pieces) {
      whole.set(piece, at);
      at += piece.length;
    }
    const zipped = new Response(whole).body;
    if (zipped === null) return { ...empty, rows: null };
    const stream = zipped.pipeThrough(new DecompressionStream('gzip'));
    const raw = new Uint8Array(await new Response(stream).arrayBuffer());
    if (hex(await crypto.subtle.digest('SHA-256', raw)) !== stored.sha256)
      return { ...empty, rows: null, writing: true };
    const body = JSON.parse(new TextDecoder().decode(raw)) as {
      closings: SourceRow[];
      links: Record<string, string>;
    };
    return { ...empty, rows: body.closings, links: body.links };
  } catch {
    return { ...empty, rows: null };
  }
}

/** A lit row's school or district as the admin reads it, from the public directory. */
export interface RowName {
  /** Its NCES id: the school's, or the district's for a district id (its state's code is the
   * id's first digits; a private school's id does not say). */
  readonly id: string;
  /** The school's name (or the district's, for a district id), cased as the map shows it. */
  readonly name: string;
  /** The school's district: its id and name; null for a district id or a school in none. */
  readonly district: { readonly id: string; readonly name: string } | null;
}

/**
 * The name of the school (or district) a lit row's NCES id names, in `directory`; null without
 * a directory, or for an id it does not have (the row then shows its id alone).
 */
export function rowName(directory: Directory | null, nces: string): RowName | null {
  if (directory === null) return null;
  const school = directory.schoolIndex(nces);
  if (school >= 0) {
    const raw = directory.meta.names[school];
    if (raw === undefined) return null;
    const at = directory.district[school] ?? -1;
    const id = at >= 0 ? directory.meta.districts.ids[at] : undefined;
    const name = at >= 0 ? directory.meta.districts.names[at] : undefined;
    return {
      id: nces,
      name: casedName(raw),
      district:
        id === undefined || name === undefined
          ? null
          : { id, name: casedName(name, { district: true }) },
    };
  }
  const district = directory.districtIndex(nces);
  const raw = district >= 0 ? directory.meta.districts.names[district] : undefined;
  if (raw === undefined) return null;
  return { id: nces, name: casedName(raw, { district: true }), district: null };
}
