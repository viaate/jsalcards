import { flushSync, mount } from 'svelte';

import App from './App.svelte';
import { takeStaticShell } from './shell/static-shell';

/*
 * The first frame comes from index.html alone: inline critical CSS, the static
 * shell and the inline still. Nothing imported here may link a stylesheet,
 * because Vite would add it to <head> as render-blocking; App.svelte has no
 * <style> for the same reason.
 */

const target = document.getElementById('app');
if (target === null) {
  throw new Error('Snowlight: missing #app mount point in index.html');
}

/**
 * Swaps the static shell for the live one, in one task: the task after this
 * module has run, so the browser is not held up by both at once. The static
 * shell takes typing meanwhile, and what was typed carries over.
 */
function start(root: HTMLElement): void {
  const staticShell = takeStaticShell(root);
  mount(App, {
    target: root,
    props: { still: staticShell?.still ?? null, initialQuery: staticShell?.query ?? '' },
  });
  // Run onMount now, so the live shell has adopted the still before the static one goes.
  flushSync();
  staticShell?.retire(root);
}
setTimeout(() => {
  start(target);
}, 0);

/*
 * Nothing else is linked: the inline critical CSS carries every rule of
 * src/styles/global.css (e2e/shell.spec.ts checks the tokens match), and no
 * text is set in the mono face. A stylesheet linked now would only make the
 * browser style and lay out the whole page again as the map starts.
 */
