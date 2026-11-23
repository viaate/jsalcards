/**
 * Another mode than Schools marked on the page's root: its data-mode, which the page's head sets
 * before the first paint for a link to one (index.html) and the modes' host keeps (modes/host.ts).
 *
 * A school layer, the glow among them, that goes on while the mark is there goes on hidden, so no
 * school draws under that mode's first frames. Whatever takes the mark off shows each such layer
 * again here: the host showing Schools, or no host at all (no map, the app's or the host's code
 * that could not load). Schools then never shows its key over a map with its own marks hidden.
 * Spelled here, apart from the modes' code, so Schools' code never pulls the modes' chunk in.
 */

/** The map calls a layer hidden here needs. */
export interface HidingMap {
  getLayer(id: string): unknown;
  getLayoutProperty(id: string, name: string): unknown;
  setLayoutProperty(id: string, name: string, value: unknown): unknown;
}

function root(): Partial<HTMLElement> | null | undefined {
  // Read as loosely as a test's stand-in page allows.
  return typeof document === 'undefined' ? undefined : document.documentElement;
}

/** Whether another mode than Schools is marked on the root. */
export function otherModeMarked(): boolean {
  return root()?.dataset?.mode !== undefined;
}

/** The layers hidden while the mark is on, each with its map, to show when it comes off. */
const waiting = new Map<string, HidingMap>();
let watcher: MutationObserver | null = null;

/** Shows every layer hidden under the mark, once the mark is off. */
function markOff(): void {
  if (otherModeMarked()) return;
  watcher?.disconnect();
  watcher = null;
  const shown = [...waiting];
  waiting.clear();
  for (const [id, map] of shown) {
    try {
      if (map.getLayer(id) !== undefined && map.getLayoutProperty(id, 'visibility') === 'none')
        map.setLayoutProperty(id, 'visibility', 'visible');
    } catch {
      // A layer that went with a style change: the next style's go on as the mark says.
    }
  }
}

/**
 * Hides layer `id`, just put on `map`, while another mode is marked, until the mark comes off by
 * any path. Returns whether it hid it.
 */
export function hideWhileMarked(map: HidingMap, id: string): boolean {
  const page = root();
  if (page?.dataset?.mode === undefined) return false;
  try {
    map.setLayoutProperty(id, 'visibility', 'none');
  } catch {
    return false;
  }
  waiting.set(id, map);
  if (watcher === null && typeof MutationObserver !== 'undefined' && page instanceof Node) {
    watcher = new MutationObserver(markOff);
    watcher.observe(page, { attributes: true, attributeFilter: ['data-mode'] });
  }
  return true;
}

/** Whether layer `id` waits for the mark to come off (for tests). */
export function waitsForMarkOff(id: string): boolean {
  return waiting.has(id);
}
