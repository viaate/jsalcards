/**
 * Builds a directory's same-place index off the page's thread
 * (same-places.ts samePlaces): it is sent the places, in millionths of a
 * degree, a part at a time, then the schools lit by the light that asked for
 * it, and answers first with the schools that light covers, worked out
 * straight from the places (same-places-build.ts coveredNow), then with the
 * index, all handed over rather than copied, so the page looks nothing up
 * for that light and marks them while the index is built. Parts out of order, or the lit
 * schools before the last part, are answered with no index, and the page
 * builds it itself.
 */
import { coveredNow, samePlacesNow } from './same-places-build';

interface Scope {
  onmessage: ((event: MessageEvent<unknown>) => void) | null;
  postMessage(message: unknown, transfer?: Transferable[]): void;
}

const scope = globalThis as unknown as Scope;

/** The places so far, and how many of their numbers are in. */
let places: Int32Array | null = null;
let filled = 0;

/** Tells the page the places did not come in whole: it builds the index itself. */
function refuse(): void {
  places = null;
  filled = 0;
  scope.postMessage({ refused: true });
}

scope.onmessage = (event) => {
  const { part, at, length, lit } = (event.data ?? {}) as Record<string, unknown>;
  if (part instanceof Int32Array && typeof at === 'number' && typeof length === 'number') {
    if (at === 0 && Number.isInteger(length) && length >= 0 && length % 2 === 0) {
      places = new Int32Array(length);
      filled = 0;
    }
    if (places === null || at !== filled || length !== places.length) {
      refuse();
      return;
    }
    if (filled + part.length > places.length) {
      refuse();
      return;
    }
    places.set(part, filled);
    filled += part.length;
    return;
  }
  if (!(lit instanceof Int32Array)) return;
  const whole = places;
  if (whole === null) {
    refuse();
    return;
  }
  if (filled !== whole.length) {
    refuse();
    return;
  }
  // The schools the light covers first, worked out straight from the places, so the page
  // marks them while the index for the lights after it is built.
  const covered = coveredNow(whole, lit);
  scope.postMessage({ covered }, [covered.buffer] as ArrayBuffer[]);
  const { start, near, shared } = samePlacesNow(whole);
  scope.postMessage({ start, near, shared }, [start.buffer, near.buffer] as ArrayBuffer[]);
};
