import { describe, expect, it } from 'vitest';

import { LABEL_GAP, announcesRoom, placeLabels } from '../chart-labels';
import type { LabelPlacement, LabelSize } from '../chart-labels';

/** Where a bar's dashed line runs across a plot `width` wide of `count` bars, as the chart draws it. */
const lineAt = (bar: number, count: number, width: number): number => ((bar + 0.3) / count) * width;

/** Labels measured at 15 px Geist in the panel, rounded up. */
const ANSWER: LabelSize = { width: 245, height: 22 };
const SHORT_ANSWER: LabelSize = { width: 180, height: 22 };
const LONG_ANSWER: LabelSize = { width: 285, height: 22 };
const ANNOUNCES: LabelSize = { width: 190, height: 22 };
const LONG_ANNOUNCES: LabelSize = { width: 205, height: 22 };

/** The desktop panel's plot, a 390 px phone's and a 320 px phone's. */
const DESK = 418;
const PHONE = 358;
const NARROW = 288;

interface Night {
  readonly width: number;
  readonly count: number;
  readonly announces: number | null;
  readonly buses?: LabelSize;
  readonly announcesLabel?: LabelSize;
}

/**
 * The announcement's label as the page lays it out: no wider than its room, its words wrapping
 * onto a second line of 22 px where they would be.
 */
function fitted(words: LabelSize, busesAt: number): LabelSize {
  const room = announcesRoom(busesAt);
  return words.width <= room ? words : { width: room, height: words.height * 2 };
}

function place(night: Night): LabelPlacement & {
  busesAt: number;
  announcesAt: number | null;
  words: LabelSize;
} {
  const { width, count, announces } = night;
  const busesAt = lineAt(count - 1, count, width);
  const announcesAt = announces === null ? null : lineAt(announces, count, width);
  const words = fitted(night.announcesLabel ?? ANNOUNCES, busesAt);
  return {
    ...placeLabels({
      width,
      busesAt,
      announcesAt,
      buses: night.buses ?? ANSWER,
      announces: announces === null ? null : words,
    }),
    busesAt,
    announcesAt,
    words,
  };
}

/**
 * What the rule promises, whatever the night: both labels inside the plot; on one line only
 * with room between them; the announcement's on the second line clear of the buses' dashed line,
 * which passes through it; and each dashed line starting under its own label.
 */
function expectClear(night: Night): void {
  const placed = place(night);
  const buses = night.buses ?? ANSWER;
  const { words } = placed;
  const label = JSON.stringify(night);
  expect(placed.buses.left, label).toBeGreaterThanOrEqual(0);
  expect(placed.buses.left + buses.width, label).toBeLessThanOrEqual(night.width);
  // The answer's dashed line drops from under it.
  expect(placed.busesAt, label).toBeGreaterThanOrEqual(placed.buses.left);
  expect(placed.busesLine, label).toBeGreaterThan(buses.height);
  const { announces, announcesAt } = placed;
  if (announces === null || announcesAt === null) {
    expect(night.announces, label).toBeNull();
    expect(placed.height, label).toBe(buses.height);
    return;
  }
  const right = announces.left + words.width;
  expect(announces.left, label).toBeGreaterThanOrEqual(0);
  expect(right, label).toBeLessThanOrEqual(night.width);
  if (announces.top === 0) {
    // Side by side: room between the two.
    expect(right + LABEL_GAP, label).toBeLessThanOrEqual(placed.buses.left);
  } else {
    // Under the buses' label, clear of its dashed line.
    expect(announces.top, label).toBeGreaterThanOrEqual(buses.height);
    expect(right + LABEL_GAP, label).toBeLessThanOrEqual(placed.busesAt + 0.001);
  }
  expect(placed.height, label).toBe(Math.max(buses.height, announces.top + words.height));
  expect(placed.announcesLine, label).toBeGreaterThan(announces.top + words.height);
  // Its own dashed line starts under it: at an end, or under its words where it could not.
  if (announcesAt <= placed.busesAt - LABEL_GAP) {
    expect(announcesAt, label).toBeGreaterThanOrEqual(announces.left - 0.001);
    expect(announcesAt, label).toBeLessThanOrEqual(right + 0.001);
  }
}

describe('the chart’s labels', () => {
  it('sets the answer at the plot’s right end and the announcement ending at its line under it', () => {
    // The night the panel shows: eleven bars, announcing at 5:30 before 7 AM buses.
    const desk = place({ width: DESK, count: 11, announces: 8.5 });
    expect(desk.buses).toEqual({ left: DESK - ANSWER.width, top: 0 });
    expect(desk.announces).toEqual({ left: (desk.announcesAt ?? 0) - ANNOUNCES.width, top: 30 });
    expect(desk.height).toBe(52);
    expect(desk.busesLine).toBe(24);
    expect(desk.announcesLine).toBe(54);
    for (const width of [NARROW, PHONE, DESK]) expectClear({ width, count: 11, announces: 8.5 });
  });

  it('keeps the two apart with the announcement 30 minutes before the buses', () => {
    for (const width of [NARROW, PHONE, DESK]) {
      const placed = place({ width, count: 11, announces: 9.5 });
      // Ending at its own line, to the left of the buses' line.
      expect(placed.announces?.left).toBeCloseTo((placed.announcesAt ?? 0) - ANNOUNCES.width);
      expectClear({ width, count: 11, announces: 9.5 });
    }
    // Eighteen bars on a 320 px phone: the two lines are LABEL_GAP apart, and still clear.
    const tight = place({ width: NARROW, count: 18, announces: 16.5 });
    expect(tight.busesAt - (tight.announcesAt ?? 0)).toBeCloseTo(LABEL_GAP);
    expect(tight.announces?.left).toBeCloseTo((tight.announcesAt ?? 0) - ANNOUNCES.width);
    expectClear({ width: NARROW, count: 18, announces: 16.5 });
    // Closer than that, it keeps clear of the buses' line rather than end at its own.
    const closer = place({ width: NARROW, count: 18, announces: 16.75 });
    expect((closer.announces?.left ?? 0) + ANNOUNCES.width).toBeCloseTo(closer.busesAt - LABEL_GAP);
    expectClear({ width: NARROW, count: 18, announces: 16.75 });
  });

  it('starts the announcement at its line when it falls in the first hour', () => {
    for (const width of [NARROW, PHONE, DESK]) {
      const placed = place({ width, count: 11, announces: 0.5 });
      expect(placed.announces?.left).toBeCloseTo(placed.announcesAt ?? -1);
      // Under the answer: side by side, the two would meet.
      expect(placed.announces?.top).toBe(30);
      expectClear({ width, count: 11, announces: 0.5 });
    }
    // With a short answer on the desktop panel, both fit on one line.
    const one = place({ width: DESK, count: 11, announces: 0.5, buses: SHORT_ANSWER });
    expect(one.announces).toEqual({ left: one.announcesAt, top: 0 });
    expect(one.height).toBe(22);
    expectClear({ width: DESK, count: 11, announces: 0.5, buses: SHORT_ANSWER });
  });

  it('keeps long words inside the plot, at every width', () => {
    for (const width of [NARROW, PHONE, DESK]) {
      for (const announces of [0, 0.5, 1.5, 4, 5.5, 8.5, 9.5, 10]) {
        expectClear({
          width,
          count: 11,
          announces,
          buses: LONG_ANSWER,
          announcesLabel: LONG_ANNOUNCES,
        });
      }
    }
    // Words longer than the plot wrap inside it, and the announcement goes under them.
    const wrapped = place({
      width: NARROW,
      count: 11,
      announces: 5,
      buses: { width: NARROW, height: 44 },
    });
    expect(wrapped.buses).toEqual({ left: 0, top: 0 });
    expect(wrapped.announces?.top).toBe(52);
    expect(wrapped.busesLine).toBe(46);
  });

  it('with no room either side of its line, sets the announcement as near it as it can', () => {
    // Mid-plot on a 320 px phone, words too long to end at the line or start there.
    const placed = place({
      width: NARROW,
      count: 11,
      announces: 4,
      announcesLabel: { width: 150, height: 22 },
    });
    expect(placed.announces).toEqual({ left: 0, top: 30 });
    expectClear({
      width: NARROW,
      count: 11,
      announces: 4,
      announcesLabel: { width: 150, height: 22 },
    });
    // Two bars on a 320 px phone: it wraps in the room left of the answer's line, under the answer.
    const two = place({ width: NARROW, count: 2, announces: 0 });
    expect(two.words).toEqual({ width: announcesRoom(two.busesAt), height: 44 });
    expect(two.announces).toEqual({ left: 0, top: 30 });
    expect(two.height).toBe(74);
    expectClear({ width: NARROW, count: 2, announces: 0 });
  });

  it('sets the answer alone on one line with no announcement', () => {
    const placed = place({ width: PHONE, count: 11, announces: null });
    expect(placed).toMatchObject({ announces: null, announcesLine: null, height: 22 });
    expectClear({ width: PHONE, count: 11, announces: null });
  });

  it('holds for any night, at any width, wherever the announcement falls', () => {
    for (const width of [NARROW, 320, PHONE, 390, DESK]) {
      for (let count = 2; count <= 18; count += 1) {
        // Every half hour, one bar an hour.
        for (let announces = 0; announces <= count - 1; announces += 0.5) {
          for (const buses of [SHORT_ANSWER, ANSWER, LONG_ANSWER]) {
            for (const announcesLabel of [ANNOUNCES, LONG_ANNOUNCES]) {
              expectClear({ width, count, announces, buses, announcesLabel });
            }
          }
        }
      }
    }
  });
});
