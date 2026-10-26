/**
 * The screen check (?diag=1): the numbers that tell why a device shows the
 * page as it does (ui/Diagnostics.svelte), over the page for its owner to send
 * in a screenshot. Started with the app's services (app/boot.ts), after the
 * first paint, so the page's first script carries none of it; its code loads
 * only when the address asks for it.
 */
import { mount } from 'svelte';

/** Whether the address asks for the screen check: ?diag=1, and nothing else. */
export function asksForDiagnostics(search: string = location.search): boolean {
  try {
    return new URLSearchParams(search).get('diag') === '1';
  } catch {
    return false;
  }
}

/** Shows the screen check in `target` when the address asks for it; nothing otherwise. */
export function startDiagnostics(
  target: Element | null = document.getElementById('app'),
  search: string = location.search,
): void {
  if (target === null || !asksForDiagnostics(search)) return;
  import('../ui/Diagnostics.svelte').then(
    ({ default: Diagnostics }) => {
      mount(Diagnostics, { target });
    },
    () => undefined,
  );
}
