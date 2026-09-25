import { flushSync, mount } from 'svelte';

import App from './App.svelte';
import { afterFirstPaint } from './shell/paint';
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

const staticShell = takeStaticShell(target);
mount(App, {
  target,
  props: { still: staticShell?.still ?? null, initialQuery: staticShell?.query ?? '' },
});
// Run onMount now, so the live shell has adopted the still before the static one goes.
flushSync();
staticShell?.retire(target);

// Shared styles and the mono face are not needed for the first frame.
void afterFirstPaint().then(() =>
  Promise.all([import('./styles/global.css'), import('@fontsource-variable/geist-mono')]),
);
