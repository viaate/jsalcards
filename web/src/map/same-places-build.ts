/**
 * Which schools of a directory stand at one place, for the glow (glow-mount.ts):
 * a school it does not light at the place of one it lights gives way to that
 * light, so no white dot shows through it.
 *
 * Two schools are at one place where they are as near as a school's panel
 * calls "Same place" in its Nearby list (copy-format.ts apart): under
 * SAME_PLACE_METRES apart in whole metres, as the details round them
 * (scripts/stage-data.mjs nearbyOf, metresBetween on points.bin's places).
 * Most such schools share the very same millionths of a degree (one
 * building, one campus); a few stand a metre apart. The places are read in
 * millionths of a degree, as points.bin keeps them (data/directory.ts e6):
 * integers, so even code the page has not made fast yet makes little garbage
 * for the collector to stop the page for.
 *
 * The index is worked out once for each directory, never as the page starts:
 * the first light asks for it (same-places.ts), and it is built in its
 * worker (same-places-worker.ts), or where no worker starts on the page in
 * short slices, so no light waits on it, and it is in a few tens of
 * milliseconds later. A light made before it is done covers no school, and
 * is covered as soon as it is (glow-mount.ts): a tap there opens the lit
 * school all the same (school-taps.ts), and every status still comes from
 * each school's own row.
 */

/** Schools under this many whole metres apart stand at one place (copy-format.ts apart). */
export const SAME_PLACE_METRES = 2;

/**
 * For each school of a directory, by its place in it, the others at its place:
 * school i's are `near[start[i]]` up to `near[start[i + 1]]`, none for most.
 */
export interface SamePlaces {
  readonly start: Int32Array;
  readonly near: Int32Array;
  /** How many schools have another at their place. */
  readonly shared: number;
}

const EARTH_RADIUS_METRES = 6_371_008.8;

/**
 * Whether two places, in degrees, are at one place as the panel says it: the
 * metres between them as the details work them out (data/details-format.ts
 * metresBetween, the same haversine on the same radius, written out here so
 * the glow's chunk does not share one with the details'), rounded.
 */
export function atOnePlace(lon1: number, lat1: number, lon2: number, lat2: number): boolean {
  const rad = Math.PI / 180;
  const h =
    Math.sin(((lat2 - lat1) * rad) / 2) ** 2 +
    Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(((lon2 - lon1) * rad) / 2) ** 2;
  const metres = 2 * EARTH_RADIUS_METRES * Math.asin(Math.min(1, Math.sqrt(h)));
  return Math.round(metres) < SAME_PLACE_METRES;
}

/*
 * The places are bucketed in cells of 2^LON_SHIFT by 2^LAT_SHIFT millionths
 * of a degree (about 20 m by 14 m, so a cell holds few schools however
 * crowded a city), and each school is checked against the others in its
 * cell, and in the next cells over only when it is within reach of that
 * edge: LAT_REACH and LON_REACH millionths, a little more than the 1.5 m that
 * rounds to 2, north and south, and east and west as far north as 78 degrees
 * (the directory's schools are all south of 72).
 */
const LON_SHIFT = 8;
const LAT_SHIFT = 7;
const LON_CELL = 1 << LON_SHIFT;
const LAT_CELL = 1 << LAT_SHIFT;
const LAT_REACH = 16;
const LON_REACH = 72;

/** Schools a slice checks between looks at the clock: a fraction of a millisecond's work, cold. */
const CHECK_EVERY = 128;
/** Numbers of a fresh table written through between looks at the clock: 64 pages of memory. */
const TOUCH_EVERY = 65_536;

/**
 * Builds a directory's index slice by slice: `step` works until `stop` says
 * so (looked at every CHECK_EVERY schools) and gives the index once done.
 */
export class SamePlacesBuild {
  private readonly places: Int32Array;
  private readonly count: number;
  /**
   * Each cell's slot, three numbers side by side (so a look at a slot reads one place in
   * memory): its column, its row, and its first school plus one (0 for a free slot). Made,
   * and each of its pages first written, in slices of their own before any school is placed:
   * a first write to fresh memory costs the page a fault, and so many at once a slice.
   */
  private slots = new Int32Array(0);
  /** Each school's next in its cell, -1 for the last. */
  private next = new Int32Array(0);
  private readonly cellMask: number;
  /** The pairs found so far, two schools each. */
  private pairs = new Int32Array(1024);
  private pairCount = 0;
  /** Each school's count of others at its place, then where its list starts. */
  private start: Int32Array | null = null;
  private shared = 0;
  /** How many of the pairs' schools are counted so far. */
  private counted = 0;
  /** The lists, and how many pairs are in them so far. */
  private near: Int32Array | null = null;
  private filled = 0;
  private phase: 'tables' | 'cells' | 'pairs' | 'lists' = 'tables';
  private at = 0;
  private result: SamePlaces | null = null;

  constructor(places: Int32Array) {
    this.places = places;
    const count = places.length >> 1;
    this.count = count;
    let bits = 4;
    while (1 << bits < count * 2) bits++;
    this.cellMask = (1 << bits) - 1;
  }

  /**
   * What it is at: making its tables, placing schools in cells, finding pairs, or making the
   * lists (for the bench).
   */
  get stage(): 'tables' | 'cells' | 'pairs' | 'lists' {
    return this.phase;
  }

  /** The index once built, else null with more to do. */
  step(stop: () => boolean): SamePlaces | null {
    while (this.result === null) {
      if (this.phase === 'tables') this.tables(stop);
      else if (this.phase === 'cells') this.cells(stop);
      else if (this.phase === 'pairs') this.findPairs(stop);
      else this.result = this.finish(stop);
      if (this.result === null && stop()) return null;
    }
    return this.result;
  }

  /** The slot of the cell at column x, row y: its own, or the free one it would take. */
  private slotOf(x: number, y: number): number {
    const { slots, cellMask } = this;
    // Small integers throughout (every step under 2^30), so even code the page has not made
    // fast yet makes no garbage: each 9 bits of a column or row times its own odd number, which
    // spreads a directory of up to half a million schools over its table.
    let slot =
      (((x & 0x1ff) * 0x2f1) ^
        ((y & 0x1ff) * 0x1d3) ^
        (((x >> 9) & 0x1ff) * 0x97) ^
        (((y >> 9) & 0x1ff) * 0x161) ^
        (((x >> 18) & 0x1ff) * 0x3b) ^
        (((y >> 18) & 0x1ff) * 0x25)) &
      cellMask;
    while (slots[slot * 3 + 2] !== 0 && (slots[slot * 3] !== x || slots[slot * 3 + 1] !== y)) {
      slot = (slot + 1) & cellMask;
    }
    return slot;
  }

  /**
   * The tables made and written through, TOUCH_EVERY numbers between looks at the clock: the
   * slots first, then each school's next.
   */
  private tables(stop: () => boolean): void {
    if (this.slots.length === 0) {
      this.slots = new Int32Array((this.cellMask + 1) * 3);
      this.at = 0;
      if (stop()) return;
    }
    let i = this.at;
    const { slots } = this;
    while (i < slots.length) {
      const end = Math.min(slots.length, i + TOUCH_EVERY);
      slots.fill(0, i, end);
      i = end;
      if (i < slots.length && stop()) {
        this.at = i;
        return;
      }
    }
    if (this.next.length !== this.count) {
      this.next = new Int32Array(this.count);
      this.next.fill(-1);
    }
    this.phase = 'cells';
    this.at = 0;
  }

  private cells(stop: () => boolean): void {
    const { places, slots, next, count } = this;
    let i = this.at;
    while (i < count) {
      const end = Math.min(count, i + CHECK_EVERY);
      for (; i < end; i++) {
        const x = places[i * 2] ?? 0;
        const y = places[i * 2 + 1] ?? 0;
        const slot = this.slotOf(x >> LON_SHIFT, y >> LAT_SHIFT);
        if (slots[slot * 3 + 2] === 0) {
          slots[slot * 3] = x >> LON_SHIFT;
          slots[slot * 3 + 1] = y >> LAT_SHIFT;
        }
        next[i] = (slots[slot * 3 + 2] ?? 0) - 1;
        slots[slot * 3 + 2] = i + 1;
      }
      if (i < count && stop()) break;
    }
    this.at = i;
    if (i === count) {
      this.phase = 'pairs';
      this.at = 0;
    }
  }

  /** Checks school i against the schools of a cell, from its school `first` on. */
  private against(i: number, first: number): void {
    const { next, places } = this;
    const x = places[i * 2] ?? 0;
    const y = places[i * 2 + 1] ?? 0;
    for (let j = first; j >= 0; j = next[j] ?? -1) {
      const dx = (places[j * 2] ?? 0) - x;
      const dy = (places[j * 2 + 1] ?? 0) - y;
      if (dx > LON_REACH || dx < -LON_REACH || dy > LAT_REACH || dy < -LAT_REACH) continue;
      // In degrees as the directory reads them (data/directory.ts), for the metres between.
      if (
        (dx !== 0 || dy !== 0) &&
        !atOnePlace(x * 1e-6, y * 1e-6, (x + dx) * 1e-6, (y + dy) * 1e-6)
      ) {
        continue;
      }
      if (this.pairCount * 2 + 2 > this.pairs.length) {
        const grown = new Int32Array(this.pairs.length * 2);
        grown.set(this.pairs);
        this.pairs = grown;
      }
      this.pairs[this.pairCount * 2] = i;
      this.pairs[this.pairCount * 2 + 1] = j;
      this.pairCount++;
    }
  }

  /** The first school, or -1, of the cell at column x, row y. */
  private firstIn(x: number, y: number): number {
    return (this.slots[this.slotOf(x, y) * 3 + 2] ?? 0) - 1;
  }

  private findPairs(stop: () => boolean): void {
    const { places, next, count } = this;
    let i = this.at;
    while (i < count) {
      const end = Math.min(count, i + CHECK_EVERY);
      for (; i < end; i++) {
        // In its own cell, the schools after it (each pair once); then the cells east, north,
        // north-east and north-west, where it is near that edge: a pair across the other edges
        // is found from the school on their far side.
        const first = next[i] ?? -1;
        if (first >= 0) this.against(i, first);
        const x = places[i * 2] ?? 0;
        const y = places[i * 2 + 1] ?? 0;
        const cx = x >> LON_SHIFT;
        const cy = y >> LAT_SHIFT;
        const east = x - cx * LON_CELL >= LON_CELL - LON_REACH;
        const west = x - cx * LON_CELL < LON_REACH;
        const north = y - cy * LAT_CELL >= LAT_CELL - LAT_REACH;
        if (!east && !north) continue;
        if (east) this.against(i, this.firstIn(cx + 1, cy));
        if (north) {
          this.against(i, this.firstIn(cx, cy + 1));
          if (east) this.against(i, this.firstIn(cx + 1, cy + 1));
          if (west) this.against(i, this.firstIn(cx - 1, cy + 1));
        }
      }
      if (i < count && stop()) break;
    }
    this.at = i;
    if (i === count) this.phase = 'lists';
  }

  /**
   * The lists from the pairs, in three steps, each stopping when told: each
   * school's count of others at its place; the counts summed, so each
   * school's entry is where its list ends; and the pairs put in, each entry
   * stepping back to where its list starts.
   */
  private finish(stop: () => boolean): SamePlaces | null {
    const { count, pairs, pairCount } = this;
    let start = this.start;
    if (start === null) {
      start = new Int32Array(count + 1);
      this.start = start;
      this.counted = 0;
      this.at = 0;
      if (stop()) return null;
    }
    let q = this.counted;
    while (q < pairCount * 2) {
      const end = Math.min(pairCount * 2, q + CHECK_EVERY * 8);
      for (; q < end; q++) {
        const school = pairs[q] ?? 0;
        start[school] = (start[school] ?? 0) + 1;
      }
      this.counted = q;
      if (stop()) return null;
    }
    let i = this.at;
    while (i < count) {
      const end = Math.min(count, i + CHECK_EVERY * 4);
      for (; i < end; i++) {
        const own = start[i] ?? 0;
        if (own !== 0) this.shared++;
        start[i] = own + (i === 0 ? 0 : (start[i - 1] ?? 0));
      }
      this.at = i;
      if (stop()) return null;
    }
    let near = this.near;
    if (near === null) {
      near = new Int32Array(pairCount * 2);
      this.near = near;
      start[count] = pairCount * 2;
      this.filled = 0;
      if (stop()) return null;
    }
    let p = this.filled;
    while (p < pairCount) {
      const end = Math.min(pairCount, p + CHECK_EVERY * 4);
      for (; p < end; p++) {
        const a = pairs[p * 2] ?? 0;
        const b = pairs[p * 2 + 1] ?? 0;
        const atA = (start[a] ?? 0) - 1;
        const atB = (start[b] ?? 0) - 1;
        near[atA] = b;
        near[atB] = a;
        start[a] = atA;
        start[b] = atB;
      }
      this.filled = p;
      if (p < pairCount && stop()) return null;
    }
    return { start, near, shared: this.shared };
  }
}

/** The index for these places, built at once: for tests, the bench and the audit. */
export function samePlacesNow(places: Int32Array): SamePlaces {
  const built = new SamePlacesBuild(places).step(() => false);
  if (built === null) throw new Error('same-places: an unbounded build stopped');
  return built;
}

/**
 * The schools at the places of these lit ones that are not lit themselves, each once, by their
 * places in the directory: what the glow covers for a light (glow-mount.ts), worked out in the
 * worker beside the index, for the light that asked for it (same-places-worker.ts).
 */
export function coveredBy(index: SamePlaces, lit: Int32Array): Int32Array {
  const { start, near } = index;
  const count = start.length - 1;
  // 1 for a lit school, 2 for one already found.
  const seen = new Uint8Array(count);
  for (const school of lit) if (school >= 0 && school < count) seen[school] = 1;
  const found: number[] = [];
  for (const school of lit) {
    if (school < 0 || school >= count) continue;
    const to = start[school + 1] ?? 0;
    for (let k = start[school] ?? 0; k < to; k++) {
      const other = near[k] ?? -1;
      if (other < 0 || other >= count || seen[other] !== 0) continue;
      seen[other] = 2;
      found.push(other);
    }
  }
  return Int32Array.from(found);
}

/**
 * The schools at the places of these lit ones that are not lit themselves, each once, worked out
 * straight from the places, with no index: the lit schools put in cells as the build puts every
 * school (so a few thousand, not the directory), then each school of the directory checked
 * against the lit ones of its cell, and of the next cells over where it is within reach of that
 * edge, as the build pairs them. The same schools as coveredBy gives with the index (in another
 * order), in a fraction of the build's time: the worker answers a page's first light with them
 * before it builds the index for the lights after it (same-places-worker.ts).
 *
 * With `among`, only those schools are checked, not the whole directory: the
 * later-day rings ask which of theirs a light covers (data/later-days.ts), so
 * no ring shows through a light the glow covers its school with.
 */
export function coveredNow(
  places: Int32Array,
  lit: Int32Array,
  among?: ArrayLike<number>,
): Int32Array {
  const count = places.length >> 1;
  let bits = 4;
  while (1 << bits < lit.length * 2) bits++;
  const mask = (1 << bits) - 1;
  // Each cell's slot: its column, its row, and its first lit school plus one (0 for free).
  const slots = new Int32Array((mask + 1) * 3);
  const next = new Int32Array(lit.length).fill(-1);
  const slotOf = (x: number, y: number): number => {
    // As the build spreads its cells (SamePlacesBuild slotOf).
    let slot =
      (((x & 0x1ff) * 0x2f1) ^
        ((y & 0x1ff) * 0x1d3) ^
        (((x >> 9) & 0x1ff) * 0x97) ^
        (((y >> 9) & 0x1ff) * 0x161) ^
        (((x >> 18) & 0x1ff) * 0x3b) ^
        (((y >> 18) & 0x1ff) * 0x25)) &
      mask;
    while (slots[slot * 3 + 2] !== 0 && (slots[slot * 3] !== x || slots[slot * 3 + 1] !== y)) {
      slot = (slot + 1) & mask;
    }
    return slot;
  };
  // 1 for a lit school, 2 for one found.
  const seen = new Uint8Array(count);
  for (let k = 0; k < lit.length; k++) {
    const school = lit[k] ?? -1;
    if (school < 0 || school >= count || seen[school] === 1) continue;
    seen[school] = 1;
    const x = places[school * 2] ?? 0;
    const y = places[school * 2 + 1] ?? 0;
    const slot = slotOf(x >> LON_SHIFT, y >> LAT_SHIFT);
    if (slots[slot * 3 + 2] === 0) {
      slots[slot * 3] = x >> LON_SHIFT;
      slots[slot * 3 + 1] = y >> LAT_SHIFT;
    }
    next[k] = (slots[slot * 3 + 2] ?? 0) - 1;
    slots[slot * 3 + 2] = k + 1;
  }
  // Each lit school's cell and the eight round it marked in a grid of cells folded 1,024 by
  // 1,024 (a cell elsewhere that folds onto one is looked at for nothing), so a school far from
  // any lit one is passed over at a glance: most of the directory, most days.
  const near8 = new Uint8Array(1 << 20);
  for (const school of lit) {
    if (school < 0 || school >= count) continue;
    const cx = (places[school * 2] ?? 0) >> LON_SHIFT;
    const cy = (places[school * 2 + 1] ?? 0) >> LAT_SHIFT;
    for (let a = -1; a <= 1; a++) {
      for (let b = -1; b <= 1; b++) near8[(((cx + a) & 1023) << 10) | ((cy + b) & 1023)] = 1;
    }
  }
  let found = new Int32Array(64);
  let foundCount = 0;
  /** Whether school j, at (x, y), is at the place of a lit school in the cell at column cx, row cy. */
  const near = (x: number, y: number, cx: number, cy: number): boolean => {
    for (let k = (slots[slotOf(cx, cy) * 3 + 2] ?? 0) - 1; k >= 0; k = next[k] ?? -1) {
      const school = lit[k] ?? 0;
      const dx = (places[school * 2] ?? 0) - x;
      const dy = (places[school * 2 + 1] ?? 0) - y;
      if (dx > LON_REACH || dx < -LON_REACH || dy > LAT_REACH || dy < -LAT_REACH) continue;
      if (dx === 0 && dy === 0) return true;
      if (atOnePlace(x * 1e-6, y * 1e-6, (x + dx) * 1e-6, (y + dy) * 1e-6)) return true;
    }
    return false;
  };
  const checked = among === undefined ? count : among.length;
  for (let n = 0; n < checked; n++) {
    const j = among === undefined ? n : (among[n] ?? -1);
    if (j < 0 || j >= count) continue;
    const x = places[j * 2] ?? 0;
    const y = places[j * 2 + 1] ?? 0;
    const cx = x >> LON_SHIFT;
    const cy = y >> LAT_SHIFT;
    if (near8[((cx & 1023) << 10) | (cy & 1023)] === 0 || seen[j] !== 0) continue;
    const east = x - cx * LON_CELL >= LON_CELL - LON_REACH;
    const west = x - cx * LON_CELL < LON_REACH;
    const north = y - cy * LAT_CELL >= LAT_CELL - LAT_REACH;
    const south = y - cy * LAT_CELL < LAT_REACH;
    let at = near(x, y, cx, cy);
    for (let a = -1; a <= 1 && !at; a++) {
      if ((a === -1 && !west) || (a === 1 && !east)) continue;
      for (let b = -1; b <= 1 && !at; b++) {
        if ((a === 0 && b === 0) || (b === -1 && !south) || (b === 1 && !north)) continue;
        at = near(x, y, cx + a, cy + b);
      }
    }
    if (!at) continue;
    seen[j] = 2;
    if (foundCount === found.length) {
      const grown = new Int32Array(found.length * 2);
      grown.set(found);
      found = grown;
    }
    found[foundCount++] = j;
  }
  return found.slice(0, foundCount);
}
