/**
 * A share card's model: what a Story or Post image of a school's day says,
 * taken from the panel's own view (app/school.ts SchoolView) at the moment
 * of the share, and nothing else. Every line is the panel's line as the panel
 * words it; the card adds only the day each line is for, named in full
 * ("Tuesday, Jan 12"), and when its lines were current ("As of 6:55 AM"), from
 * the same files at the same moment (SchoolView.share). A view with nothing
 * current to say (still loading, a past day, no status and no chance) has no
 * card (app/share-offer.ts). No source is named.
 */

import type { StatusKey } from '../copy';
import { shareFormat } from '../copy-share';
import type { CardKind, CardWords } from '../copy-share';
import type { StatusLine } from './chance';
import type { SchoolView } from './school';
import { cardOffered, shownLines } from './share-offer';

export type { CardKind } from '../copy-share';

/** Each card's size in pixels: a story's 9:16, a post's 4:5. */
export const CARD_SIZES: Readonly<
  Record<CardKind, { readonly width: number; readonly height: number }>
> = Object.freeze({
  story: Object.freeze({ width: 1080, height: 1920 }),
  post: Object.freeze({ width: 1080, height: 1350 }),
});

/** A card's color: a status's own, the chance's, or none. */
export type CardTone = StatusKey | 'open' | 'chance' | 'none';

/** One status line of the card: the panel's words, with the day it is for. */
export interface CardLine {
  readonly tone: StatusKey | 'open';
  /** "Closed today", as the panel says it. */
  readonly headline: string;
  /** "Tuesday, Jan 12", the day it is for; null where the line names its own. */
  readonly day: string | null;
  /** "2-hour delay · Starts at 10:00 AM", as the panel says it, or null. */
  readonly detail: string | null;
  /** "Winter storm", the reason the panel gives, or null. */
  readonly reason: string | null;
  /** "Buses run snow routes. No breakfast.", the plain details the panel says, or null. */
  readonly said: string | null;
}

/** The chance, as the panel's chance section says it. */
export interface CardChance {
  /** "64%". */
  readonly number: string;
  /** "Chance of no school Tuesday". */
  readonly meaning: string;
  /** "Tuesday, Jan 13", the day the chance is for, named in full: a card outlasts its week. */
  readonly day: string;
  /** "Few local records", where the panel says it, or null. */
  readonly fewRecords: string | null;
}

export interface CardModel {
  readonly id: string;
  readonly name: string;
  readonly campus: string | null;
  /** "Kansas City, MO · Jackson County", or null. */
  readonly place: string | null;
  readonly tone: CardTone;
  readonly lines: readonly CardLine[];
  readonly chance: CardChance | null;
  /** The season line, as the panel says it, or null. */
  readonly season: string | null;
  /** "As of 6:55 AM": every card says something current (a status or a chance), as of when. */
  readonly asOf: string;
  /** The site's host, as the link names it: "snowlightmap.com". */
  readonly host: string;
  /** The card's answer in a few words, for the share's text (its alt): who, what, which day, as of when. */
  readonly alt: string;
}

export interface CardInput {
  readonly view: SchoolView;
  /** The link the card is shared with (`?school=ID`). */
  readonly url: string;
  readonly now: Date;
  /** The viewer's time zone. */
  readonly timeZone: string;
}

function cardLine(line: StatusLine): CardLine {
  const day = line.day ?? null;
  return {
    tone: line.tone,
    headline: line.headline,
    day: day === null ? null : shareFormat.cardDay(day),
    detail: line.detail,
    reason: line.reason ?? null,
    said: line.said,
  };
}

/** The card's color: the first decided status's, else the chance's, else open's. */
function toneOf(lines: readonly CardLine[], chance: CardChance | null): CardTone {
  const decided = lines.find((line) => line.tone !== 'open');
  if (decided !== undefined) return decided.tone;
  if (chance !== null) return 'chance';
  return lines.length > 0 ? 'open' : 'none';
}

/** The earlier of the times given: a card is as current as its oldest line. */
function earliest(times: readonly (Date | null)[]): Date | null {
  let found: Date | null = null;
  for (const at of times) {
    if (at !== null && (found === null || at.getTime() < found.getTime())) found = at;
  }
  return found;
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return '';
  }
}

/**
 * The card for a school's panel as it shows now, or null where the panel offers
 * none (app/share-offer.ts cardOffered): a view still loading, one without its
 * share facts (a past day), one with nothing to say of the school's day, or a
 * line or chance without the time it was current at.
 */
export function cardModel(input: CardInput): CardModel | null {
  const { view, url, now, timeZone } = input;
  const facts = view.share ?? null;
  if (!cardOffered(view) || facts === null) return null;
  const lines = shownLines(view).map(cardLine);
  const chance: CardChance | null =
    view.chance === null
      ? null
      : {
          number: shareFormat.percent(view.chance.number),
          meaning: view.chance.meaning,
          day: shareFormat.cardDay(view.chance.day),
          fewRecords: view.chance.fewRecords,
        };
  const at = earliest([
    lines.length > 0 ? facts.statusAt : null,
    chance === null ? null : facts.chanceAt,
  ]);
  if (at === null) return null;
  // On the school's clock; on the viewer's, named, where the school's cannot be read (its
  // zone not read yet, or none): the time is true either way (copy-share.ts asOf).
  const asOf = shareFormat.asOf(at, { school: facts.zone, viewer: timeZone }, now);
  const season = view.season ?? null;
  const words: CardWords = {
    name: view.name,
    campus: view.campus,
    lines,
    chance,
    asOf,
  };
  return {
    id: view.id,
    name: view.name,
    campus: view.campus,
    place: view.place,
    tone: toneOf(lines, chance),
    lines,
    chance,
    season,
    asOf,
    host: hostOf(url),
    alt: shareFormat.alt(words),
  };
}
