import { describe, expect, it } from 'vitest';

import { GlowStatus } from '../color';
import { mercatorXFromLng, mercatorYFromLat } from '../mercator';
import {
  OFFSET_BORN,
  OFFSET_HI,
  OFFSET_LO,
  OFFSET_STATUS,
  type PackClock,
  PackScratch,
  STATIC_BORN_SECONDS,
  STRIDE_BYTES,
  packPoints,
} from '../pack';

const { Closed, Delayed, Remote, EarlyDismissal, Open } = GlowStatus;

/** A clock for packs that carry no born times. */
const CLOCK: PackClock = { originMs: 0, nowMs: 0 };

function record(bytes: Uint8Array, slot: number) {
  const view = new DataView(bytes.buffer, bytes.byteOffset + slot * STRIDE_BYTES, STRIDE_BYTES);
  return {
    x: view.getFloat32(OFFSET_HI, true) + view.getFloat32(OFFSET_LO, true),
    y: view.getFloat32(OFFSET_HI + 4, true) + view.getFloat32(OFFSET_LO + 4, true),
    hiX: view.getFloat32(OFFSET_HI, true),
    born: view.getFloat32(OFFSET_BORN, true),
    status: view.getUint8(OFFSET_STATUS),
    padding: [21, 22, 23].map((offset) => view.getUint8(offset)),
  };
}

describe('packPoints', () => {
  const lngLat = new Float32Array([
    -93.1,
    44.9, // 0 open
    -87.6,
    41.8, // 1 closed
    -71.0,
    42.3, // 2 delayed
    -104.9,
    39.7, // 3 remote
    -122.3,
    47.6, // 4 early dismissal
    -84.4,
    33.7, // 5 closed
    -90.2,
    38.6, // 6 open
  ]);
  const status = new Uint8Array([Open, Closed, Delayed, Remote, EarlyDismissal, Closed, Open]);

  it('puts glowing points first in draw order (closed last, on top) and open points after', () => {
    const packed = packPoints({ lngLat, status }, CLOCK);
    expect(packed.count).toBe(7);
    expect(packed.glowCount).toBe(5);
    expect(packed.openCount).toBe(2);
    expect(packed.dropped).toBe(0);
    const statuses = Array.from({ length: packed.count }, (_, i) => record(packed.bytes, i).status);
    expect(statuses).toEqual([EarlyDismissal, Remote, Delayed, Closed, Closed, Open, Open]);
    // Stable within a status, and order maps every record back to its input row.
    expect(Array.from(packed.order)).toEqual([4, 3, 2, 1, 5, 0, 6]);
  });

  it('stores float32 hi and lo parts that add back to the float64 mercator position', () => {
    const packed = packPoints({ lngLat, status }, CLOCK);
    for (let slot = 0; slot < packed.count; slot++) {
      const row = packed.order[slot] ?? 0;
      const lng = lngLat[row * 2] ?? 0;
      const lat = lngLat[row * 2 + 1] ?? 0;
      const r = record(packed.bytes, slot);
      expect(Math.abs(r.x - mercatorXFromLng(lng))).toBeLessThan(1e-13);
      expect(Math.abs(r.y - mercatorYFromLat(lat))).toBeLessThan(1e-13);
      expect(Math.fround(r.hiX)).toBe(r.hiX);
      expect(r.padding).toEqual([0, 0, 0]);
    }
  });

  it('accepts precomputed mercator coordinates', () => {
    const mercator = new Float64Array([0.25, 0.375, 0.3, 0.4]);
    const packed = packPoints({ mercator, status: new Uint8Array([Closed, Remote]) }, CLOCK);
    const [first, second] = [record(packed.bytes, 0), record(packed.bytes, 1)];
    expect(first.status).toBe(Remote);
    expect(first.x).toBeCloseTo(0.3, 14);
    expect(first.y).toBeCloseTo(0.4, 14);
    expect(second).toMatchObject({ x: 0.25, y: 0.375, status: Closed });
  });

  it('converts bornAt to seconds on the layer clock and marks missing ones static', () => {
    const bornAt = new Float64Array([NaN, 12_500, NaN, Infinity, 14_000, -Infinity, NaN]);
    const packed = packPoints({ lngLat, status, bornAt }, { originMs: 10_000, nowMs: 20_000 });
    const bySlot = (row: number): number => record(packed.bytes, packed.order.indexOf(row)).born;
    expect(bySlot(1)).toBeCloseTo(2.5, 6);
    expect(bySlot(4)).toBeCloseTo(4, 6);
    for (const row of [0, 3, 5]) expect(bySlot(row)).toBe(STATIC_BORN_SECONDS);
    expect(packed.lastBornSeconds).toBeCloseTo(4, 6);
    expect(packed.bornClamped).toBe(0);
    expect(packPoints({ lngLat, status }, CLOCK).lastBornSeconds).toBe(STATIC_BORN_SECONDS);
  });

  it('pulses a bornAt later than now in at once: skewed clocks and epoch milliseconds', () => {
    const originMs = 5_000;
    const nowMs = 125_000;
    const nowSeconds = (nowMs - originMs) / 1000;
    const epochMs = Date.UTC(2026, 0, 15, 12); // Date.now() passed by mistake
    const bornAt = new Float64Array([
      nowMs + 4_000, // a server clock 4 s ahead
      epochMs,
      nowMs - 500, // half a second ago: kept as is
      epochMs + 1,
      nowMs, // exactly now
      NaN,
      nowMs + 0.001,
    ]);
    const packed = packPoints({ lngLat, status, bornAt }, { originMs, nowMs });
    const bySlot = (row: number): number => record(packed.bytes, packed.order.indexOf(row)).born;

    for (const row of [0, 1, 3, 4, 6]) {
      expect(bySlot(row)).toBeLessThanOrEqual(nowSeconds);
      expect(bySlot(row)).toBe(Math.fround(nowSeconds));
    }
    expect(bySlot(2)).toBeCloseTo(nowSeconds - 0.5, 4);
    expect(bySlot(5)).toBe(STATIC_BORN_SECONDS);
    expect(packed.lastBornSeconds).toBeLessThanOrEqual(nowSeconds);
    expect(packed.lastBornSeconds).toBe(nowSeconds);
    // Rows 0, 1, 3 and 6 were in the future; row 4 is exactly now.
    expect(packed.bornClamped).toBe(4);
  });

  it('never stores a born time the shader clock has not reached', () => {
    // However the origin and now fall, the stored float32 never passes float32(now).
    for (const [originMs, nowMs] of [
      [0, 0],
      [0, 123_456.789],
      [98_765.4321, 3_600_000.123],
      [1.5, 86_400_000 * 7],
    ] as const) {
      const bornAt = new Float64Array(7).fill(nowMs + 60_000);
      const packed = packPoints({ lngLat, status, bornAt }, { originMs, nowMs });
      const nowSeconds = (nowMs - originMs) / 1000;
      for (let slot = 0; slot < packed.count; slot++) {
        expect(record(packed.bytes, slot).born).toBeLessThanOrEqual(Math.fround(nowSeconds));
      }
      expect(packed.lastBornSeconds).toBeLessThanOrEqual(nowSeconds);
      expect(packed.bornClamped).toBe(7);
    }
  });

  it('drops rows with a bad coordinate or status code and counts them', () => {
    const packed = packPoints(
      {
        lngLat: new Float32Array([NaN, 40, -90, 95, -90, 40, -90, 40, -200, 40]),
        status: new Uint8Array([Closed, Closed, 5, Delayed, Closed]),
      },
      CLOCK,
    );
    expect(packed.count).toBe(1);
    expect(packed.dropped).toBe(4);
    expect(Array.from(packed.order)).toEqual([3]);
  });

  it('rejects mismatched or ambiguous input', () => {
    const one = new Uint8Array([Closed]);
    expect(() => packPoints({ status: one }, CLOCK)).toThrow(/lngLat or mercator/);
    expect(() =>
      packPoints(
        { lngLat: new Float32Array(2), mercator: new Float32Array(2), status: one },
        CLOCK,
      ),
    ).toThrow(/not both/);
    expect(() => packPoints({ lngLat: new Float32Array(4), status: one }, CLOCK)).toThrow(
      /coordinates/,
    );
    expect(() =>
      packPoints({ lngLat: new Float32Array(2), status: one, bornAt: new Float32Array(2) }, CLOCK),
    ).toThrow(/bornAt/);
  });

  it('reuses its scratch buffer when data is replaced with the same or fewer points', () => {
    const scratch = new PackScratch();
    const big = 150_000;
    const bigSet = {
      lngLat: new Float32Array(big * 2).fill(40).map((v, i) => (i % 2 === 0 ? -95 : v)),
      status: new Uint8Array(big),
    };
    const first = packPoints(bigSet, CLOCK, scratch);
    const buffer = scratch.buffer;
    expect(first.count).toBe(big);
    expect(first.bytes.byteLength).toBe(big * STRIDE_BYTES);
    const second = packPoints({ lngLat, status }, CLOCK, scratch);
    expect(scratch.buffer).toBe(buffer);
    expect(second.bytes.buffer).toBe(buffer);
    expect(second.bytes.byteLength).toBe(7 * STRIDE_BYTES);
    packPoints(bigSet, CLOCK, scratch);
    expect(scratch.buffer).toBe(buffer);
  });
});
