/**
 * The airport code tags (flights spec LR-F11, LR-F12): who wins a crowded spot, each airport's
 * place on the board, and each tag drawn as one image (LR-F13). The airports here are made up.
 */
import { validateStyleMin } from '@maplibre/maplibre-gl-style-spec';
import type { StyleSpecification } from '@maplibre/maplibre-gl-style-spec';
import { describe, expect, it } from 'vitest';

import type { Airport, LiveRead } from '../data';
import {
  LAYER_ORDER,
  ROUTE_SOURCE,
  TAG_EDGE,
  airportLayers,
  boardRanks,
  dotStates,
  dotStatesInTurns,
  tagBox,
  meets,
  placeTags,
  settleTags,
  spotBox,
  textSize,
  tagOrder,
} from '../layer';
import type { Colors, TagSpot } from '../layer';
import { airportLive, liveFile } from './fixtures';

function airport(code: string, lat: number, lon: number, perDay: number): Airport {
  return { code, name: code, city: code, state: 'MO', lat, lon, tz: 'America/Chicago', perDay };
}

/** MapLibre places the lowest symbol-sort-key first, so it wins an overlap. */
function winner(a: { risk: number; rank: number }, b: { risk: number; rank: number }): 'a' | 'b' {
  return tagOrder(a.risk, a.rank) < tagOrder(b.risk, b.rank) ? 'a' : 'b';
}

describe('a crowded spot', () => {
  it('goes to a small airport at high risk over a big calm one beside it', () => {
    expect(winner({ risk: 2, rank: 300 }, { risk: 0, rank: 0 })).toBe('a');
  });

  it('goes to some risk over calm, and high risk over some', () => {
    expect(winner({ risk: 1, rank: 350 }, { risk: 0, rank: 1 })).toBe('a');
    expect(winner({ risk: 1, rank: 0 }, { risk: 2, rank: 358 })).toBe('b');
  });

  it('goes to the busier airport when both are at the same risk', () => {
    expect(winner({ risk: 2, rank: 4 }, { risk: 2, rank: 40 })).toBe('a');
    expect(winner({ risk: 0, rank: 9 }, { risk: 0, rank: 2 })).toBe('b');
  });
});

describe('the board', () => {
  const big = airport('ORD', 41.98, -87.9, 1200);
  const sister = airport('MDW', 41.79, -87.75, 300);
  const far = airport('MCI', 39.3, -94.71, 250);

  it('ranks a metro by all its airports, its sister keeping its own place', () => {
    const ranks = boardRanks([far, sister, big]);
    expect(ranks.get('ORD')).toBe(0);
    // MDW keeps its own 300, still busier than MCI's 250.
    expect(ranks.get('MDW')).toBe(1);
    expect(ranks.get('MCI')).toBe(2);
  });

  it('lets a sister airport in trouble win over its calm metro lead', () => {
    const ranks = boardRanks([big, sister]);
    expect(
      winner({ risk: 2, rank: ranks.get('MDW') ?? 99 }, { risk: 0, rank: ranks.get('ORD') ?? 99 }),
    ).toBe('a');
  });

  it('keeps the same order between frames for airports that tie, by code', () => {
    const a = airport('BBB', 30, -100, 50);
    const b = airport('AAA', 35, -110, 50);
    expect([...boardRanks([a, b]).entries()]).toEqual([...boardRanks([b, a]).entries()]);
    expect(boardRanks([a, b]).get('AAA')).toBe(0);
  });
});

describe('placing the tags', () => {
  const view = { width: 400, height: 800 };
  const spot = (code: string, x: number, risk: number, rank: number) => ({
    code,
    x,
    y: 100,
    width: 40,
    height: 16,
    order: tagOrder(risk, rank),
  });

  it('gives a crowded spot to the airport in trouble, then to the busier one', () => {
    const codes = (spots: ReturnType<typeof spot>[]): string[] =>
      placeTags(spots, view).map((each) => each.code);
    // A small airport at high risk beside a big calm one: the small one shows.
    expect(codes([spot('ORD', 100, 0, 0), spot('MDW', 110, 2, 40)])).toEqual(['MDW']);
    // Both at the same risk: the busier one.
    expect(codes([spot('MDW', 110, 2, 40), spot('ORD', 100, 2, 0)])).toEqual(['ORD']);
    // Room for both: both, never over each other.
    expect(codes([spot('ORD', 100, 0, 0), spot('MCI', 200, 0, 9)]).sort()).toEqual(['MCI', 'ORD']);
  });

  it('never lets two tags overlap, and leaves out those off the view', () => {
    const spots = Array.from({ length: 60 }, (_, i) => spot(`A${String(i)}`, i * 9 - 30, i % 3, i));
    const placed = placeTags(spots, view);
    for (const a of placed)
      for (const b of placed)
        if (a !== b)
          expect(
            Math.abs(a.x - b.x) >= (a.width + b.width) / 2 ||
              Math.abs(a.y - b.y) >= (a.height + b.height) / 2,
          ).toBe(true);
    expect(placed.every((each) => each.x + each.width / 2 >= 0)).toBe(true);
    // The same each time, whatever order they come in: no tag flickers.
    expect(placeTags([...spots].reverse(), view)).toEqual(placed);
  });

  it('sizes a tag from the face’s advances, so it keeps its size once the face is in', () => {
    // No pip or dot in a tag (LR-F18.1): every tag is its code and its padding alone.
    const plain = tagBox('MCI');
    expect(plain.start).toBe(5);
    expect(plain.width).toBeCloseTo(plain.start + plain.text + 5, 5);
    expect(tagBox('ORD').width).toBeGreaterThan(tagBox('IAH').width);
    expect(plain.start + plain.text).toBeLessThan(plain.width);
    expect(textSize(2)).toBe(10);
    expect(textSize(9)).toBe(12);
  });
});

describe('the layers as they go on the map', () => {
  /** A theme's colors, as colors() reads them from the page's tokens. */
  const COLORS: Colors = {
    lowTag: '#3a3a3a',
    low: '#a3a3a3',
    delay: '#ffc46b',
    cancel: '#7fd4ff',
    label: '#a3a3a3',
    surface: '#111111',
    hairline: '#2a2a2a',
    text1: '#f5f5f5',
    text3: '#6b6b6b',
    bg: '#000000',
    surfaceHigh: '#0a0a0a',
    onClosed: '#000000',
  };

  it('are each valid as MapLibre reads a style, since they go on unchecked', () => {
    const layers = airportLayers(COLORS, 'schools');
    const style: StyleSpecification = {
      version: 8,
      glyphs: 'https://example.invalid/{fontstack}/{range}.pbf',
      sources: {
        [ROUTE_SOURCE]: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
      },
      layers: [...layers.values()].map((placed) => placed.layer),
    };
    expect(validateStyleMin(style)).toEqual([]);
  });

  it('are only the route’s line, under the schools: no airport layer and no new program', () => {
    // The airports go on the overlay: a symbol, circle or text layer of Flights' own would make
    // the map build a WebGL program at start (LR-F13). The line draws only with an arc.
    const layers = airportLayers(COLORS, 'schools');
    expect([...layers.keys()]).toEqual([...LAYER_ORDER]);
    expect([...layers.values()].map((placed) => [placed.layer.type, placed.before])).toEqual([
      ['line', 'schools'],
    ]);
  });
});

/** A read of a live file with many airports, a third of them at a high risk of a cancel. */
function liveRead(): LiveRead {
  const high: [number, number, number, number, number] = [300, 300, 300, 300, 300];
  const airports = Array.from({ length: 60 }, (_, i) => {
    const entry = airportLive(`A${String(i).padStart(2, '0')}`, '2026-01-05');
    return i % 3 === 0
      ? { ...entry, dep_canc: [high, high, high] as typeof entry.dep_canc }
      : entry;
  });
  const file = liveFile(airports, '2026-01-05T13:50:00Z');
  return {
    file,
    byCode: new Map(airports.map((entry) => [entry.code, entry])),
    at: Date.parse(file.generated_at),
    named: true,
  };
}

describe('every airport’s dot, reckoned in turns', () => {
  it('gives the same states as all at once', async () => {
    const read = liveRead();
    const zones = new Map(read.file.airports.map((entry) => [entry.code, 'America/Chicago']));
    const at = Date.parse('2026-01-05T14:00:00Z');
    expect(await dotStatesInTurns(read, zones, at)).toEqual(dotStates(read, zones, at));
    expect(await dotStatesInTurns(null, zones, at)).toEqual(new Map());
  });
});

describe('where each tag goes', () => {
  const view = { width: 400, height: 300 };
  const spot = (code: string, x: number, y: number, rank = 0): TagSpot => ({
    code,
    x,
    y,
    width: 30,
    height: 16,
    order: tagOrder(0, rank),
  });

  it('keeps a tag on its airport where it has room', () => {
    expect(settleTags([spot('MCI', 200, 150)], view, [])).toEqual([spot('MCI', 200, 150)]);
  });

  it('sets a tag beside its airport, off the page’s box it would sit under', () => {
    const legend = { x0: 170, y0: 120, x1: 260, y1: 160 };
    const [moved] = settleTags([spot('MCI', 185, 168)], view, [legend]);
    expect(moved).toBeDefined();
    if (moved === undefined) return;
    expect(meets(spotBox(moved), legend)).toBe(false);
    expect(Math.abs(moved.x - 185) + Math.abs(moved.y - 168)).toBeLessThan(40);
  });

  it('hides a tag with no room about its airport, but never the open airport’s', () => {
    const everywhere = { x0: 0, y0: 0, x1: 400, y1: 300 };
    expect(settleTags([spot('MCI', 200, 150)], view, [everywhere])).toEqual([]);
    const open = { ...spot('MCI', 200, 150), order: -1 };
    expect(settleTags([open], view, [everywhere])).toEqual([open]);
  });

  it('never draws a tag cut off at the view’s edges or under the page’s boxes', () => {
    const header = { x0: 0, y0: 0, x1: 400, y1: 40 };
    const spots = [spot('SMF', 2, 150), spot('OMA', 200, 30), spot('LNK', 398, 290)];
    const settled = settleTags(spots, view, [header]);
    expect(settled.length).toBeGreaterThan(0);
    for (const each of settled) {
      const box = spotBox(each);
      expect(box.x0).toBeGreaterThanOrEqual(TAG_EDGE);
      expect(box.y0).toBeGreaterThanOrEqual(TAG_EDGE);
      expect(box.x1).toBeLessThanOrEqual(view.width - TAG_EDGE);
      expect(box.y1).toBeLessThanOrEqual(view.height - TAG_EDGE);
      expect(meets(box, header)).toBe(false);
    }
  });

  it('never lets two set tags meet, the same each time', () => {
    const panel = { x0: 150, y0: 140, x1: 250, y1: 160 };
    const spots = Array.from({ length: 12 }, (_, i) => spot(`A${String(i)}`, 120 + i * 14, 150, i));
    const settled = settleTags(placeTags(spots, view), view, [panel]);
    for (const a of settled)
      for (const b of settled) if (a !== b) expect(meets(spotBox(a), spotBox(b))).toBe(false);
    expect(settleTags(placeTags(spots, view), view, [panel])).toEqual(settled);
  });
});
