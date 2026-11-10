// @vitest-environment node
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { copy } from '../../copy';
import { chanceFormat } from '../../copy-chance';
import { detailsFormat } from '../../copy-details';
import { format } from '../../copy-format';
import { shareCopy, shareFormat } from '../../copy-share';
import { NO_STATUS } from '../../data/school-day';
import { UNKNOWN_ZONE, UNREAD_ZONE } from '../../data/map-day';
import { cardModel } from '../share-card';
import type { CardModel } from '../share-card';
import { cardOffered } from '../share-offer';
import type { SchoolView, ViewInput } from '../school';
import { A_CLOSINGS, A_NOW, A_OUTLOOK, ZONE } from './chance-fixtures';
import {
  CLOSED,
  CLOSED_TWO_DAYS,
  DELAYED,
  EVENING_PREDICTIONS_AT,
  LONG_SCHOOL,
  MORNING,
  MORNING_CLOSINGS,
  REMOTE,
  SCHOOL,
  SEASON,
  URL_OF,
  viewOf,
} from './share-card-fixtures';

const NBSP = ' ';

function card(view: SchoolView, now = MORNING, timeZone = ZONE): CardModel {
  const model = cardModel({ view, url: URL_OF(view.id), now, timeZone });
  if (model === null) throw new Error('no card');
  return model;
}

// The house style lives in scripts/check-copy.mjs, a plain Node module (see src/copy.test.ts).
const checkCopy = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../scripts/check-copy.mjs',
);
const problems = (await import(/* @vite-ignore */ checkCopy)) as {
  problems: (text: string, file?: string) => string[];
};

describe('a share card, from the panel’s view', () => {
  it('says a closed school’s day as the panel does, with the day named and as of when', () => {
    const view = viewOf({ status: CLOSED });
    const model = card(view);
    expect(model.name).toBe(view.name);
    expect(model.place).toBe(view.place);
    expect(model.tone).toBe('closed');
    expect(model.lines).toEqual([
      {
        tone: 'closed',
        headline: copy.statusLine.closed.today,
        day: 'Monday, Jan 12',
        detail: null,
        reason: copy.reason.winterStorm,
        said: null,
      },
    ]);
    // Every word of the line is the panel's own.
    expect(model.lines[0]?.headline).toBe(view.status[0]?.headline);
    expect(view.status[0]?.note).toContain(copy.reason.winterStorm);
    expect(model.chance).toBeNull();
    expect(model.asOf).toBe(`As of 6:55${NBSP}AM`);
    expect(model.host).toBe('snowlightmap.com');
    expect(model.wordmark).toBe(copy.appName);
    expect(model.initial).toBe('L');
  });

  it('says a delay’s length and start as the panel does', () => {
    const view = viewOf({ status: DELAYED });
    const model = card(view);
    expect(model.tone).toBe('delayed');
    expect(model.lines[0]?.headline).toBe(copy.statusLine.delayed.today);
    expect(model.lines[0]?.detail).toBe(view.status[0]?.detail);
    expect(model.lines[0]?.detail).toBe(format.delay(120, 600));
    expect(model.lines[0]?.reason).toBe(copy.reason.ice);
    // The plain details as the panel says them below the status, and nothing more.
    expect(model.lines[0]?.said).toBe(view.status[0]?.said);
    expect(model.lines[0]?.said).toBe(detailsFormat.said([3, 8]));
    // The share's text is short: the status, its day and its times, never the plain details.
    expect(model.alt).toContain(format.delay(120, 600));
    expect(model.alt).not.toContain(detailsFormat.said([3, 8]) ?? 'missing');
  });

  it('says remote learning in its own color', () => {
    const model = card(viewOf({ status: REMOTE }));
    expect(model.tone).toBe('remote');
    expect(model.lines.map((line) => line.headline)).toEqual([copy.statusLine.remote.today]);
    expect(model.lines[0]?.reason).toBe(copy.reason.extremeCold);
  });

  it('names each day of a school closed today and tomorrow', () => {
    const model = card(viewOf({ status: CLOSED_TWO_DAYS }));
    expect(model.lines.map((line) => [line.headline, line.day])).toEqual([
      [copy.statusLine.closed.today, 'Monday, Jan 12'],
      [copy.statusLine.closed.tomorrow, 'Tuesday, Jan 13'],
    ]);
  });

  it('gives a chance alone as the panel does, as of when its forecast was made', () => {
    const outlook =
      A_OUTLOOK === null ? null : { ...A_OUTLOOK, generatedAt: EVENING_PREDICTIONS_AT };
    const view = viewOf({ now: A_NOW, closings: A_CLOSINGS, outlook });
    expect(view.chance).not.toBeNull();
    const model = card(view, A_NOW);
    expect(model.lines).toEqual([]);
    expect(model.tone).toBe('chance');
    expect(model.chance).toEqual({
      number: '64%',
      meaning: view.chance?.meaning,
      // The day the chance is for, named in full as a status's is: a post outlasts its week.
      day: 'Tuesday, Jan 13',
      fewRecords: null,
    });
    expect(view.chance?.day).toBe('2026-01-13');
    expect(model.chance?.meaning).toBe(chanceFormat.chanceOn('2026-01-13'));
    expect(model.asOf).toBe(`As of 8:50${NBSP}PM`);
    expect(model.alt).toContain('Tuesday, Jan 13');
  });

  it('has no card for a chance without the time its forecast was made', () => {
    const view = viewOf({ now: A_NOW, closings: A_CLOSINGS, outlook: A_OUTLOOK });
    expect(view.chance).not.toBeNull();
    expect(cardModel({ view, url: URL_OF(view.id), now: A_NOW, timeZone: ZONE })).toBeNull();
  });

  it('says the day and the time of an older file: never a stale line as if current', () => {
    // The file the page holds was made the evening before, when the school had posted.
    const closings = { ...MORNING_CLOSINGS, generated_at: '2026-01-11T23:00:00Z' };
    const model = card(viewOf({ status: CLOSED, closings }));
    expect(model.lines[0]?.day).toBe('Monday, Jan 12');
    expect(model.asOf).toBe(`As of ${format.day('2026-01-11')}, 5:00${NBSP}PM`);
    expect(model.alt).toContain(model.asOf);
  });

  it('names the school’s clock where the viewer’s reads otherwise', () => {
    const view = viewOf({ status: CLOSED, timeZone: 'America/New_York' });
    const model = card(view, MORNING, 'America/New_York');
    expect(model.asOf).toBe(`As of 6:55${NBSP}AM${NBSP}CT`);
  });

  it('carries the season line where the panel shows one, and none where it does not', () => {
    const counted = viewOf({ status: CLOSED, season: SEASON });
    expect(counted.season).not.toBeNull();
    expect(card(counted).season).toBe(counted.season);
    // On the card's face, not in the share's short text.
    expect(card(counted).alt).not.toContain(counted.season ?? 'none');
    expect(card(viewOf({ status: CLOSED })).season).toBeNull();
  });

  it('keeps a long name whole, for the card to wrap', () => {
    const view = viewOf({ record: LONG_SCHOOL, id: LONG_SCHOOL.id, status: CLOSED });
    const model = card(view);
    expect(model.name).toBe(view.name);
    expect(model.name.length).toBeGreaterThan(60);
  });

  it('has no card where the panel has no status and no chance: never a nameplate alone', () => {
    const view = viewOf({ status: NO_STATUS });
    expect(view.share).not.toBeNull();
    expect(cardOffered(view)).toBe(false);
    expect(cardModel({ view, url: URL_OF(view.id), now: MORNING, timeZone: ZONE })).toBeNull();
  });

  it('says as of when on the viewer’s clock, named, where the school’s clock is not read yet', () => {
    // The predictions file shipped but not held for the directory (not read yet, a failed
    // fetch, a stamp for another directory): the school's clock is UNREAD_ZONE, and its panel
    // still says its status, by the day that is today everywhere.
    for (const zone of [UNREAD_ZONE, UNKNOWN_ZONE, null, 'Not/AZone']) {
      const view = viewOf({ status: CLOSED, zone });
      expect(
        view.status.map((line) => line.headline),
        String(zone),
      ).toEqual([copy.statusLine.closed.today]);
      expect(cardOffered(view), String(zone)).toBe(true);
      const central = card(view, MORNING, 'America/Chicago');
      expect(central.asOf, String(zone)).toBe(`As of 6:55${NBSP}AM${NBSP}CT`);
      const eastern = card(view, MORNING, 'America/New_York');
      expect(eastern.asOf, String(zone)).toBe(`As of 7:55${NBSP}AM${NBSP}ET`);
      // The day only where the panel names one: UNKNOWN_ZONE's line names none.
      expect(central.lines[0]?.day, String(zone)).toBe(
        view.status[0]?.day === null ? null : 'Monday, Jan 12',
      );
    }
    // And a viewer's clock this browser cannot read: UTC, named.
    const view = viewOf({ status: CLOSED, zone: UNREAD_ZONE });
    expect(card(view, MORNING, 'Not/AZone').asOf).toBe(`As of 12:55${NBSP}PM${NBSP}UTC`);
  });

  it('is offered exactly where its model is made, for every state the panel can be in', () => {
    const outlook =
      A_OUTLOOK === null ? null : { ...A_OUTLOOK, generatedAt: EVENING_PREDICTIONS_AT };
    const replay = {
      day: '2026-01-05',
      lookup: () => ({ status: 0, reason: 0 }),
    } as unknown as NonNullable<ViewInput['replay']>;
    const views: SchoolView[] = [];
    for (const zone of [ZONE, UNREAD_ZONE, UNKNOWN_ZONE, null, 'Not/AZone']) {
      for (const status of [NO_STATUS, CLOSED, DELAYED, REMOTE, CLOSED_TWO_DAYS]) {
        views.push(viewOf({ status, zone }));
        views.push(viewOf({ status, zone, closings: null }));
        views.push(viewOf({ status, zone, season: SEASON }));
        views.push(viewOf({ status, zone, now: A_NOW, closings: A_CLOSINGS, outlook }));
        views.push(viewOf({ status, zone, now: A_NOW, closings: A_CLOSINGS, outlook: A_OUTLOOK }));
        views.push(viewOf({ status, zone, replay }));
        views.push({ ...viewOf({ status, zone }), loading: true });
      }
    }
    let offered = 0;
    for (const view of views) {
      for (const timeZone of [ZONE, 'America/New_York', 'Not/AZone']) {
        const model = cardModel({ view, url: URL_OF(view.id), now: MORNING, timeZone });
        expect(model !== null, JSON.stringify(view.share)).toBe(cardOffered(view));
        if (model !== null) offered++;
      }
    }
    expect(offered).toBeGreaterThan(100);
  });

  it('has no card while the panel loads, or for a past day', () => {
    const loading: SchoolView = { ...viewOf({ status: CLOSED }), loading: true };
    expect(
      cardModel({ view: loading, url: URL_OF(SCHOOL.id), now: MORNING, timeZone: ZONE }),
    ).toBeNull();
    const replay = {
      day: '2026-01-05',
      lookup: () => ({ status: 0, reason: 0 }),
    } as unknown as NonNullable<ViewInput['replay']>;
    const past = viewOf({ status: CLOSED, replay });
    expect(past.share).toBeNull();
    expect(
      cardModel({ view: past, url: URL_OF(SCHOOL.id), now: MORNING, timeZone: ZONE }),
    ).toBeNull();
  });

  it('never says when a status was posted, or by whom: only the panel’s status, day and reason', () => {
    const model = card(viewOf({ status: CLOSED }));
    const said = JSON.stringify(model);
    expect(said).not.toContain(copy.detail.posted);
    expect(said).not.toContain(copy.detail.confirmed);
  });

  it('says its words in the house style, in its alt as on its face', () => {
    const outlook =
      A_OUTLOOK === null ? null : { ...A_OUTLOOK, generatedAt: EVENING_PREDICTIONS_AT };
    const models = [
      card(viewOf({ status: CLOSED, season: SEASON })),
      card(viewOf({ status: DELAYED })),
      card(viewOf({ status: REMOTE })),
      card(viewOf({ now: A_NOW, closings: A_CLOSINGS, outlook }), A_NOW),
      card(viewOf({ status: CLOSED, timeZone: 'America/New_York' }), MORNING, 'America/New_York'),
    ];
    for (const model of models) {
      // The alt's own words: what the card adds to the directory's names (which are the school's).
      const own = model.alt.slice(
        model.alt.indexOf(model.lines[0]?.headline ?? model.chance?.number ?? ''),
      );
      const texts = [
        own,
        model.asOf,
        ...model.lines.map((line) => line.day),
        model.chance?.number,
      ].filter((text): text is string => typeof text === 'string');
      for (const text of texts)
        expect(problems.problems(text, 'src/copy-share.ts'), text).toEqual([]);
    }
    for (const text of [
      shareCopy.options,
      shareCopy.story,
      shareCopy.post,
      shareCopy.saved,
      shareCopy.imageSaved,
      shareCopy.linkInstead,
      shareCopy.failed,
      shareCopy.shareLink,
    ]) {
      expect(problems.problems(text, 'src/copy-share.ts'), text).toEqual([]);
    }
    // Short, for a message beside the image: who, what and which day, and as of when.
    expect(models[0]?.alt).toBe(
      `Lantern Hill High: Closed today · Monday, Jan 12. As of 6:55${NBSP}AM.`,
    );
    expect(models[1]?.alt).toBe(
      `Lantern Hill High: Delayed start today · Monday, Jan 12 · ${format.delay(120, 600) ?? ''}. As of 6:55${NBSP}AM.`,
    );
    expect(models[3]?.alt).toBe(
      `Lantern Hill High: 64% · ${chanceFormat.chanceOn('2026-01-13')} · Tuesday, Jan 13. As of 8:50${NBSP}PM.`,
    );
    for (const model of models) {
      expect(model.alt).not.toContain(model.place ?? 'none');
      expect(model.alt).not.toContain(SEASON_LINE);
    }
  });

  it('names its saved image by the school and the card', () => {
    expect(shareFormat.fileName('A1902690', 'story')).toBe('snowlight-A1902690-story.png');
    expect(shareFormat.fileName('20/../x', 'post')).toBe('snowlight-20x-post.png');
  });
});

const SEASON_LINE = 'This school year, since Aug 1: closed 2 days, delayed 1.';
