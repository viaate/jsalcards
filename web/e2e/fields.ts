/**
 * Every field on the page that takes text and is set under 16 px, by name and size, to run in the
 * page (page.evaluate). On a touch screen none may be: iOS Safari zooms the page in on a tapped
 * field set smaller and keeps it zoomed, the left of the page off the screen. Checked with no media
 * query of its own, so a rule that misses a device or a component shows here.
 */
export function smallFields(): string[] {
  const notText = new Set([
    'checkbox',
    'radio',
    'range',
    'color',
    'file',
    'button',
    'submit',
    'reset',
    'image',
    'hidden',
  ]);
  const small: string[] = [];
  for (const field of document.querySelectorAll('input, select, textarea')) {
    if (field instanceof HTMLInputElement && notText.has(field.type)) continue;
    if (field.getBoundingClientRect().width === 0) continue;
    const size = Number.parseFloat(getComputedStyle(field).fontSize);
    if (size >= 16) continue;
    const label =
      field.getAttribute('aria-label') ??
      field.closest('label')?.textContent.trim().split('\n')[0] ??
      field.getAttribute('name') ??
      '';
    const kind = field instanceof HTMLInputElement ? field.type : field.tagName.toLowerCase();
    small.push(`${kind} "${label}" set at ${String(size)} px`);
  }
  return small;
}
