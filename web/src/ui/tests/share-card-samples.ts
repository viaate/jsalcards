/**
 * Made-up cards for the share card's tests and sample pictures
 * (scripts/share-card-samples.mjs): the design's seven samples, and the cards
 * it did not sample (every other status, the mixes of two days and a chance,
 * and the extremes of length), each as the model the card is laid out from.
 * The schools, their town and county, the statuses, the storm and the chances
 * are all invented, so no sample can be taken for a real school's day; the
 * words are the site's own, with its times as it writes them (a no-break
 * space before AM).
 */
import type { CardChance, CardKind, CardLine, CardModel } from '../../app/share-card';
import { copy } from '../../copy';
import { chanceCopy, chanceFormat } from '../../copy-chance';
import { detailsCopy } from '../../copy-details';
import { format } from '../../copy-format';
import { shareFormat } from '../../copy-share';

export interface CardSample {
  /** The picture's name: the design's own for its seven samples. */
  readonly name: string;
  readonly kind: CardKind;
  readonly model: CardModel;
  /** Whether the design drew this card (its picture has the same name). */
  readonly designed: boolean;
}

const TODAY = '2026-01-12';
const TOMORROW = '2026-01-13';
const MONDAY = shareFormat.cardDay(TODAY);
const TUESDAY = shareFormat.cardDay(TOMORROW);
const MORNING = `As of ${format.time(new Date('2026-01-12T12:55:00Z'), 'America/Chicago')}`;
const EVENING = `As of ${format.time(new Date('2026-01-13T02:50:00Z'), 'America/Chicago')}`;

/** "This school year, since Aug 1: closed 2 days, delayed 1." */
const SEASON = 'This school year, since Aug 1: closed 2 days, delayed 1.';
/** Every status counted, since a later day: the longest the line gets. */
const SEASON_FOUR =
  'This school year, since Oct 27: closed 4 days, delayed 3, remote 1, dismissed early 2.';
const SEASON_THREE = 'This school year, since Oct 27: closed 4 days, delayed 3, dismissed early 2.';

export const LONG_NAME =
  'Lantern Hill Northwest Academy for International Baccalaureate and Advanced Science Studies';
/** A hundred letters and spaces: whole on three lines only at a K under the largest. */
export const NAME_100 =
  'Lantern Hill Northwest Academy for International Baccalaureate and Advanced Science and Arts Studies';
/** One word of 80 letters: wider than the card at any size, so broken, never clipped. */
export const NAME_ONE_WORD = 'Lanternhillnorthwestacademy'.repeat(3).slice(0, 80);
/** A place of 60 characters. */
export const PLACE_60 = 'Briarwood Heights Township, KS · Wren and Sample County Line';

function line(tone: CardLine['tone'], headline: string, extra: Partial<CardLine> = {}): CardLine {
  return { tone, headline, day: MONDAY, detail: null, reason: null, said: null, ...extra };
}

const CLOSED = line('closed', copy.statusLine.closed.today, { reason: copy.reason.winterStorm });
const CLOSED_TOMORROW = line('closed', copy.statusLine.closed.tomorrow, {
  day: TUESDAY,
  reason: copy.reason.winterStorm,
});
const DELAYED = line('delayed', copy.statusLine.delayed.today, {
  detail: format.delay(120, 600),
  reason: copy.reason.ice,
  said: `${detailsCopy.said.buses_snow_routes} ${detailsCopy.said.no_breakfast}`,
});
const REMOTE = line('remote', copy.statusLine.remote.today, { reason: copy.reason.extremeCold });
const EARLY = line('earlyDismissal', copy.statusLine.earlyDismissal.today, {
  detail: format.dismissal(120, 750),
  reason: copy.reason.winterStorm,
});
const OPEN = line('open', copy.open.today);

function chance(number: string, day = TOMORROW, few = false): CardChance {
  return {
    number: shareFormat.percent(number),
    meaning: chanceFormat.chanceOn(day),
    day: shareFormat.cardDay(day),
    fewRecords: few ? chanceCopy.fewRecords : null,
  };
}

function model(extra: Partial<CardModel>): CardModel {
  const lines = extra.lines ?? [];
  const lead = lines.find((each) => each.tone !== 'open');
  return {
    id: '201164001574',
    name: 'Lantern Hill High',
    campus: null,
    place: 'Briarwood, KS · Wren County',
    tone: lead?.tone ?? ((extra.chance ?? null) === null ? 'open' : 'chance'),
    lines,
    chance: null,
    season: null,
    asOf: MORNING,
    host: 'snowlightmap.com',
    alt: '',
    ...extra,
  };
}

const closed = model({ lines: [CLOSED], season: SEASON });
const delayed = model({ lines: [DELAYED], season: SEASON });
const longTwoDays = model({ name: LONG_NAME, lines: [CLOSED, CLOSED_TOMORROW], season: SEASON });
const chanceAlone = model({ chance: chance('64'), asOf: EVENING });

/** Every plain detail the site can say of one day, as it says them. */
const EVERY_DETAIL = Object.values(detailsCopy.said).join(' ');

const both = (
  name: string,
  made: CardModel,
  kinds: readonly CardKind[] = ['story', 'post'],
): CardSample[] =>
  kinds.map((kind) => ({ name: `${name}-${kind}`, kind, model: made, designed: false }));

const design = (name: string, kind: CardKind, made: CardModel): CardSample => ({
  name,
  kind,
  model: made,
  designed: true,
});

/** The design's seven samples, by its pictures' names (the crest sample is drawn without a crest). */
export const DESIGN_SAMPLES: readonly CardSample[] = [
  design('closed-story-light', 'story', closed),
  design('closed-story-light-crest', 'story', closed),
  design('delayed-story-light', 'story', delayed),
  design('long-two-days-story-light', 'story', longTwoDays),
  design('chance-story-dark', 'story', chanceAlone),
  design('closed-post-light', 'post', closed),
  design('chance-post-dark', 'post', chanceAlone),
];

/** The cards the design did not sample. */
export const EXTRA_SAMPLES: readonly CardSample[] = [
  ...both('remote', model({ lines: [REMOTE], season: SEASON })),
  ...both('early', model({ lines: [EARLY], season: SEASON })),
  ...both('open', model({ lines: [OPEN] })),
  ...both('delayed', delayed, ['post']),
  ...both('closed-tomorrow', model({ lines: [CLOSED_TOMORROW], season: SEASON, asOf: EVENING })),
  ...both('chance-7', model({ chance: chance('7'), asOf: EVENING })),
  ...both('chance-under-1', model({ chance: chance('<1'), asOf: EVENING })),
  ...both('chance-over-99', model({ chance: chance('>99'), asOf: EVENING })),
  ...both(
    'chance-few-records',
    model({ chance: chance('64', '2026-01-14', true), season: SEASON, asOf: EVENING }),
  ),
  ...both('closed-with-chance', model({ lines: [CLOSED], chance: chance('64'), season: SEASON })),
  ...both('open-with-chance', model({ lines: [OPEN], chance: chance('64') })),
  ...both('open-then-closed', model({ lines: [OPEN, CLOSED_TOMORROW], season: SEASON })),
  ...both(
    'campus',
    model({
      name: 'The Pembroke Hill School',
      campus: 'Wornall Campus',
      place: 'Kansas City, MO · Jackson County',
      lines: [DELAYED],
      season: SEASON,
    }),
  ),
  ...both(
    'heaviest',
    model({
      name: LONG_NAME,
      lines: [
        { ...DELAYED, said: EVERY_DETAIL },
        line('earlyDismissal', copy.statusLine.earlyDismissal.tomorrow, { day: TUESDAY }),
      ],
      season: SEASON,
    }),
  ),
  ...both('name-one-word', model({ name: NAME_ONE_WORD, lines: [CLOSED], season: SEASON })),
  ...both('place-60', model({ place: PLACE_60, lines: [CLOSED], season: SEASON })),
  ...both(
    'nearby-four-counts',
    model({
      lines: [{ ...CLOSED, reason: format.reasonNearby('winterStorm', 2) }],
      season: SEASON_FOUR,
    }),
  ),
  ...both(
    'nearby-school-words',
    model({
      lines: [
        {
          ...CLOSED,
          reason: format.reasonNearby('severeStorms', 1),
          said: `${detailsCopy.said.staff_report} ${detailsCopy.said.after_school_cancelled}`,
        },
      ],
      season: SEASON_THREE,
    }),
  ),
  ...both('name-100', model({ name: NAME_100, lines: [CLOSED] })),
  ...both(
    'ff-tt',
    model({ name: 'Jefferson Little Staff Academy', lines: [CLOSED], season: SEASON }),
  ),
];

export const SAMPLES: readonly CardSample[] = [...DESIGN_SAMPLES, ...EXTRA_SAMPLES];
