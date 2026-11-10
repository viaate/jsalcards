/**
 * The share cards' words (app/share-card.ts, ui/share-card.ts): the panel's
 * share options, and what a card says beyond the panel's own lines (which it
 * shows as the panel words them). The part of src/copy.ts that loads with the
 * panel and its cards rather than with the page. The same rules hold here as
 * there, and `npm run lint:copy` reads this file as the site's copy
 * (scripts/check-copy.mjs COPY_MODULES).
 */

import { copy } from './copy.ts';
import { chanceFormat } from './copy-chance.ts';
import { format } from './copy-format.ts';

/** Recursively freezes an object graph so no string can be changed at runtime. */
function deepFreeze<T>(value: T): T {
  if (typeof value === 'object' && value !== null && !Object.isFrozen(value)) {
    for (const key of Reflect.ownKeys(value)) {
      deepFreeze((value as Record<PropertyKey, unknown>)[key]);
    }
    Object.freeze(value);
  }
  return value;
}

/** Between two parts of one line: "Closed today · Tuesday, Jan 12". */
const DOT = ' · ';
/** Holds a time to its zone: "6:55 AM CT". */
const NBSP = '\u00a0';

export const shareCopy = /* @__PURE__ */ deepFreeze({
  /** The share options under the panel's Share button. */
  options: 'Share as',
  /** A tall card, for a story (1080 by 1920). */
  story: 'Story',
  /** A shorter card, for a post (1080 by 1350). */
  post: 'Post',
  /** The existing link. */
  copyLink: copy.share.copyLink,
  /** Said on a card's button once its image is saved and the link copied, where files cannot be shared. */
  saved: 'Image saved, link copied',
  /** Said there when the image is saved but the link could not be copied. */
  imageSaved: 'Image saved',
  /** Said there when no image could be made, and the link was copied in its place. */
  linkInstead: 'No image, link copied',
  /** Said there when no image could be made, nor the link copied. */
  failed: 'No image made',
  /** The link option where the device has a share sheet: it opens the sheet with the link. */
  shareLink: 'Share link',
  /** The card's wordmark. */
  wordmark: copy.appName,
});

/** Which card: a story's, or a post's. */
export type CardKind = 'story' | 'post';

/** "Tuesday, Jan 12": the day a card's status is for, named in full. */
function cardDay(localDate: string): string {
  return `${chanceFormat.weekday(localDate)}, ${format.dateTimeFormat('monthDay', 'UTC').format(format.parseLocalDate(localDate))}`;
}

/** The clock a card falls back to where no other can be read, and its name. */
const UTC = 'UTC';

/** Whether this browser can tell the time on a clock: a zone it reads. */
function readsZone(zone: string | null): zone is string {
  if (zone === null) return false;
  try {
    format.time(new Date(0), zone);
    return true;
  } catch {
    return false;
  }
}

/**
 * When the card's lines were current: "As of 6:55 AM" on the school's clock,
 * its day too when that is not today there ("As of Mon, Jan 12, 6:55 AM"),
 * and the school's zone where the viewer's clock reads otherwise ("As of
 * 6:55 AM CT"). Where the school's clock cannot be read (its zone not read
 * yet, UNREAD_ZONE or UNKNOWN_ZONE, or none at all), the viewer's, always
 * named ("As of 7:55 AM ET"): the same moment, told truly by a clock the card
 * names.
 */
function asOf(
  at: Date,
  zones: { readonly school: string | null; readonly viewer: string },
  now: Date,
): string {
  const viewer = readsZone(zones.viewer) ? zones.viewer : UTC;
  const own = readsZone(zones.school);
  const clock = own ? zones.school : viewer;
  const when = format.time(at, clock);
  const day = format.localDay(at, clock);
  const stamp = day === format.localDay(now, clock) ? when : `${format.day(day)}, ${when}`;
  const zone = own
    ? chanceFormat.zoneAfter(at, { school: clock, viewer })
    : `${NBSP}${clock === UTC ? UTC : chanceFormat.zoneName(clock, at)}`;
  return `As of ${stamp}${zone}`;
}

/** The chance as the card's headline says it, with its sign: "64%". */
function percent(number: string): string {
  return `${number}%`;
}

/** What a card says, for the share's text (its alt). */
export interface CardWords {
  readonly name: string;
  readonly campus: string | null;
  readonly lines: readonly {
    readonly headline: string;
    readonly day: string | null;
    readonly detail: string | null;
  }[];
  readonly chance: {
    readonly number: string;
    readonly meaning: string;
    readonly day: string;
  } | null;
  readonly asOf: string;
}

/**
 * A card's answer in a few words, for the share sheet's text beside the image
 * and the link (its alt): the school, each status with its day and times, or
 * the chance with its day, and as of when. The place, reason, plain details
 * and season stay on the card's face: a message reads short.
 * "Border Star Montessori: Closed today · Monday, Jan 12. As of 6:42 AM."
 */
function alt(words: CardWords): string {
  const parts: string[] = [];
  for (const line of words.lines) {
    const said = [line.headline, line.day, line.detail].filter(
      (part): part is string => part !== null && part !== '',
    );
    parts.push(said.join(DOT));
  }
  if (words.chance !== null) {
    parts.push([words.chance.number, words.chance.meaning, words.chance.day].join(DOT));
  }
  parts.push(words.asOf);
  const name = words.campus === null ? words.name : `${words.name}${DOT}${words.campus}`;
  return `${name}: ${parts.map((part) => (/[.:]$/u.test(part) ? part : `${part}.`)).join(' ')}`;
}

/** The saved image's name: "snowlight-A1902690-story.png". */
function fileName(id: string, kind: CardKind): string {
  return `snowlight-${id.replace(/[^\w-]/gu, '')}-${kind}.png`;
}

export const shareFormat = /* @__PURE__ */ deepFreeze({
  cardDay,
  asOf,
  percent,
  alt,
  fileName,
});

export type ShareFormat = typeof shareFormat;
