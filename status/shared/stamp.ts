/** Reading when a served file was made, from its bytes. Pure. */

/** Only this much of the end of a large closings file is decoded. */
export const TAIL_BYTES = 65536;
/** A stamp file larger than this is not one. */
export const STAMP_MAX_BYTES = 1024;

export interface Stamp {
  /** The file's `generated_at` in Unix seconds; null: the checker could not read one. */
  made: number | null;
  /** The served file itself is broken. */
  bad: boolean;
  /** The chances file holds no districts. */
  blank: boolean;
}

const INSTANT = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$/;

/** Unix seconds of an instant of the form `YYYY-MM-DDTHH:MM:SSZ`, and of no other form. */
export function instant(text: unknown): number | null {
  if (typeof text !== 'string') return null;
  const found = INSTANT.exec(text);
  if (!found) return null;
  const [year, month, day, hour, minute, second] = found.slice(1).map(Number) as [
    number,
    number,
    number,
    number,
    number,
    number,
  ];
  const ms = Date.UTC(year, month - 1, day, hour, minute, second);
  // A date that does not exist (Feb 30, 25:00) rolls over: it must read back as written.
  if (new Date(ms).toISOString() !== `${text.slice(0, 19)}.000Z`) return null;
  return ms / 1000;
}

function decode(bytes: Uint8Array): string {
  return new TextDecoder().decode(bytes);
}

function closings(bytes: Uint8Array): Stamp {
  if (bytes.length <= TAIL_BYTES) {
    let made: number | null = null;
    try {
      const parsed: unknown = JSON.parse(decode(bytes));
      if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
        made = instant((parsed as Record<string, unknown>)['generated_at']);
      }
    } catch {
      made = null;
    }
    return { made, bad: made === null, blank: false };
  }
  // The file is served with sorted keys and ends `"generated_at":"…","schema_version":1}`.
  const tail = decode(bytes.subarray(bytes.length - TAIL_BYTES));
  const key = '"generated_at":"';
  const at = tail.lastIndexOf(key);
  const made = at < 0 ? null : instant(tail.slice(at + key.length, at + key.length + 20));
  return { made, bad: false, blank: false };
}

function chances(bytes: Uint8Array): Stamp {
  const none: Stamp = { made: null, bad: false, blank: false };
  if (bytes.length > STAMP_MAX_BYTES) return none;
  let parsed: unknown;
  try {
    parsed = JSON.parse(decode(bytes));
  } catch {
    return none;
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return none;
  const fields = parsed as Record<string, unknown>;
  const made = instant(fields['generated_at']);
  const districts = fields['districts'];
  if (made === null || typeof districts !== 'number' || !Number.isInteger(districts)) return none;
  if (districts < 0) return none;
  return { made, bad: false, blank: districts === 0 };
}

/**
 * When the file was made. For the closings file a small body is parsed whole and a large one
 * gives its stamp from its last bytes; for the chances the body is the stamp file.
 */
export function readStamp(part: 'closings' | 'chances', bytes: Uint8Array): Stamp {
  return part === 'closings' ? closings(bytes) : chances(bytes);
}
