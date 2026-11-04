/** The admin's Sources tab: the live reader's lit-closing sources (GET /v1/admin/sources), decoded. */

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
