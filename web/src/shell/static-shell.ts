/**
 * index.html carries a static copy of the shell so the first frame paints
 * before any script runs. main.ts mounts the Svelte shell next to it and then
 * removes it in the same task, so no frame ever shows the swap. What someone
 * did in the static shell before that (typing a search) carries over.
 */

export const STATIC_SHELL_SELECTOR = '[data-static-shell]';
const STILL_SELECTOR = 'svg.still';
const SEARCH_SELECTOR = 'input.search-input';

export interface StaticShell {
  /** The inline still, for the Svelte shell to adopt, so it is the same node throughout. */
  readonly still: SVGSVGElement | null;
  /** Text typed into the static search field. */
  readonly query: string;
  /** Removes the static shell and moves focus to the live search field if it had it. */
  retire(root: ParentNode): void;
}

export function takeStaticShell(root: ParentNode): StaticShell | null {
  const shell = root.querySelector(STATIC_SHELL_SELECTOR);
  if (shell === null) return null;

  // Left in place: the Svelte shell adopts (moves) this node when it mounts.
  const still = shell.querySelector<SVGSVGElement>(STILL_SELECTOR);
  const input = shell.querySelector<HTMLInputElement>(SEARCH_SELECTOR);
  const query = input?.value ?? '';
  const focused = input !== null && input === document.activeElement;
  const start = focused ? input.selectionStart : null;
  const end = focused ? input.selectionEnd : null;

  return {
    still,
    query,
    retire(liveRoot) {
      shell.remove();
      if (!focused) return;
      const live = liveRoot.querySelector<HTMLInputElement>(SEARCH_SELECTOR);
      if (live === null) return;
      live.focus({ preventScroll: true });
      if (start !== null && end !== null) live.setSelectionRange(start, end);
    },
  };
}
