/**
 * The panel's share cards, loaded with the first press of its Share button:
 * each card's model from the panel's view as it shows at that moment
 * (app/share-card.ts), its PNG made here in the browser (ui/share-card.ts),
 * and the share itself. On a phone that can share files (iOS Safari, Android
 * Chrome: Web Share with files) the system share sheet opens with the image
 * and the link; anywhere else the image is saved and the link copied. Nothing
 * asks for a permission.
 *
 * The cards are made as the options open, so a tap shares at once, within the
 * tap a phone's share sheet needs; a tap on a card whose panel has changed
 * since makes it again first, so a card never says what the panel no longer
 * does.
 */

import { cardModel } from '../app/share-card';
import type { CardKind, CardModel } from '../app/share-card';
import { shareFormat } from '../copy-share';
import type { SchoolView } from '../app/school';
import { renderCard } from './share-card';

export type { CardKind } from '../app/share-card';

/**
 * How a share ended: shared through the sheet, the image saved with the link copied, the
 * image saved alone (the clipboard refused the link), called off, or failed.
 */
export type ShareOutcome = 'shared' | 'saved' | 'imageSaved' | 'cancelled' | 'failed';

export interface CardSource {
  /** The panel's view as it shows now. */
  readonly view: () => SchoolView;
  /** The link to the school (`?school=ID`). */
  readonly url: () => string | null;
  readonly now?: () => Date;
  readonly timeZone?: () => string;
}

interface Made {
  readonly key: string;
  readonly model: CardModel;
  readonly blob: Promise<Blob>;
}

/** The time a card took to make, for the page's performance timeline ("share-card story"). */
export const MEASURE_PREFIX = 'share-card';

function viewerZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return 'UTC';
  }
}

/** A phone that can share an image through its share sheet. */
function canShareFile(file: File): boolean {
  if (typeof navigator.share !== 'function' || typeof navigator.canShare !== 'function')
    return false;
  if (!window.matchMedia('(pointer: coarse)').matches) return false;
  try {
    return navigator.canShare({ files: [file] });
  } catch {
    return false;
  }
}

/** Saves an image through a link the page clicks: no permission asked. */
function save(blob: Blob, name: string): void {
  const href = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = href;
  link.download = name;
  link.rel = 'noopener';
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => {
    URL.revokeObjectURL(href);
  }, 60_000);
}

export interface CardSharer {
  /** Makes both cards for the panel as it shows now, ahead of a tap. */
  prepare(): void;
  /** Whether the panel as it shows now has a card to share. */
  available(): boolean;
  /** Shares one card of the panel as it shows now. */
  share(kind: CardKind): Promise<ShareOutcome>;
}

export function createCardSharer(source: CardSource): CardSharer {
  const now = source.now ?? (() => new Date());
  const timeZone = source.timeZone ?? viewerZone;
  const made = new Map<CardKind, Made>();

  const current = (): { model: CardModel; key: string; url: string } | null => {
    const url = source.url();
    if (url === null) return null;
    const model = cardModel({ view: source.view(), url, now: now(), timeZone: timeZone() });
    return model === null ? null : { model, key: JSON.stringify(model), url };
  };

  /** The cards are made one after another: two at once would each take as long as both. */
  let queue: Promise<unknown> = Promise.resolve();

  const make = (kind: CardKind, model: CardModel, key: string): Made => {
    const found = made.get(kind);
    if (found?.key === key) return found;
    const blob = queue.then(async () => {
      const started = performance.now();
      const png = await renderCard(model, kind);
      try {
        performance.measure(`${MEASURE_PREFIX} ${kind}`, {
          start: started,
          end: performance.now(),
        });
      } catch {
        // A timeline that takes no measure: the card is made all the same.
      }
      return png;
    });
    queue = blob.catch(() => undefined);
    const entry = { key, model, blob };
    made.set(kind, entry);
    // A card that fails to make is made again at the next tap.
    blob.catch(() => {
      if (made.get(kind) === entry) made.delete(kind);
    });
    return entry;
  };

  return {
    prepare() {
      const found = current();
      if (found === null) return;
      make('story', found.model, found.key);
      make('post', found.model, found.key);
    },
    available() {
      return current() !== null;
    },
    async share(kind) {
      const found = current();
      if (found === null) return 'failed';
      const { model, key, url } = found;
      let blob: Blob;
      try {
        blob = await make(kind, model, key).blob;
      } catch {
        return 'failed';
      }
      const name = shareFormat.fileName(model.id, kind);
      const file = new File([blob], name, { type: 'image/png' });
      if (canShareFile(file)) {
        try {
          await navigator.share({ files: [file], title: model.name, text: model.alt, url });
          return 'shared';
        } catch (error) {
          if (error instanceof DOMException && error.name === 'AbortError') return 'cancelled';
          // A sheet the browser would not open (the tap's moment passed while the card was made):
          // the image saved and the link copied instead, as on a computer.
        }
      }
      save(blob, name);
      try {
        await navigator.clipboard.writeText(url);
        return 'saved';
      } catch {
        // The image is saved all the same; the link stays on the panel's Copy link.
        return 'imageSaved';
      }
    },
  };
}
