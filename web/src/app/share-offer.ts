/**
 * Whether the school panel offers a share card, by the same rule the card's
 * model (app/share-card.ts) is made by: a view that has loaded, with its share
 * facts (none for a past day), something to say (a status line or a chance),
 * and the time each of them was current at. The panel reads it before the
 * cards' code is loaded (ui/DetailPanel.svelte), so it shows Story and Post
 * only where a tap makes a card; a card's model is null exactly where this is
 * false. Kept apart from the card's code, which loads on the first press of
 * Share.
 */

import type { StatusLine } from './chance';
import type { SchoolView } from './school';

/** The status lines the panel shows: above the chance where it gives one, else on their own. */
export function shownLines(view: SchoolView): readonly StatusLine[] {
  return view.chance === null ? view.status : view.chance.status;
}

/** Whether the panel as it shows has a card to share. */
export function cardOffered(view: SchoolView): boolean {
  const facts = view.share ?? null;
  if (view.loading || view.name === '' || facts === null) return false;
  const lines = shownLines(view);
  // A nameplate alone is not a card: the panel says nothing of the school's day.
  if (lines.length === 0 && view.chance === null) return false;
  // A line or a chance without the time it was current at: no card rather than one that
  // cannot say as of when.
  if (lines.length > 0 && facts.statusAt === null) return false;
  return view.chance === null || facts.chanceAt !== null;
}
