/**
 * Keeps the account sheet and its focused field above an on-screen keyboard.
 *
 * iPhone Safari (and Chrome on Android, whose default is the same
 * `interactive-widget=resizes-visual`, set in index.html) does not shrink the
 * layout viewport for the keyboard: a sheet fixed to the bottom of the screen
 * stays where it was, under the keyboard, and only the keyboard's accessory bar
 * shows. The visual viewport does shrink, so the sheet is lifted by the gap
 * between the two bottoms and kept no taller than what is visible, and the
 * focused field is scrolled into the sheet's visible part. With no keyboard
 * (a desktop, or a phone with the keyboard down) the gap is 0 and nothing
 * changes: the sheet's own CSS places it.
 */

export interface VisualViewportLike {
  readonly height: number;
  readonly offsetTop: number;
}

export interface Lift {
  /** How far the visible area's bottom sits above the layout viewport's bottom, in CSS px. */
  readonly lift: number;
  /** The visible area's height, in CSS px. */
  readonly height: number;
}

/** The lift for a layout viewport `layoutHeight` tall, or null when nothing covers its bottom. */
export function keyboardLift(
  layoutHeight: number,
  viewport: VisualViewportLike | null,
): Lift | null {
  if (viewport === null || !(layoutHeight > 0) || !(viewport.height > 0)) return null;
  const lift = Math.round(layoutHeight - viewport.offsetTop - viewport.height);
  // Rounding, and a browser toolbar sliding by a pixel, are not a keyboard.
  if (lift < 2) return null;
  return { lift, height: Math.floor(viewport.height) };
}

/**
 * The scroll position that shows a field inside a scrolling box: the field's
 * and the box's visible edges in the same coordinates (client rects), with
 * `margin` px of room. Unchanged when the field already shows; a field taller
 * than the box shows its top.
 */
export function scrollToShow(
  scrollTop: number,
  box: { readonly top: number; readonly bottom: number },
  field: { readonly top: number; readonly bottom: number },
  margin = 12,
): number {
  if (field.top - margin < box.top)
    return Math.max(0, scrollTop - (box.top - (field.top - margin)));
  if (field.bottom + margin > box.bottom) {
    const down = field.bottom + margin - box.bottom;
    const roomAbove = field.top - margin - box.top;
    return scrollTop + Math.min(down, Math.max(0, roomAbove));
  }
  return scrollTop;
}

/**
 * Follows the visual viewport while `sheet` is open: sets --keyboard-lift and
 * --visible-height on it (read by its CSS), and keeps the focused field in
 * view. Returns the function that stops following.
 */
export function followKeyboard(sheet: HTMLElement, win: Window = window): () => void {
  const viewport = win.visualViewport;
  if (viewport === null) return () => undefined;
  let frame = 0;

  const showFocused = (): void => {
    const field = win.document.activeElement;
    if (!(field instanceof HTMLElement) || !sheet.contains(field) || field === sheet) return;
    const next = scrollToShow(
      sheet.scrollTop,
      sheet.getBoundingClientRect(),
      field.getBoundingClientRect(),
    );
    if (next !== sheet.scrollTop) sheet.scrollTop = next;
  };

  const update = (): void => {
    cancelAnimationFrame(frame);
    const layoutHeight = win.document.documentElement.clientHeight || win.innerHeight;
    const lift = keyboardLift(layoutHeight, viewport);
    if (lift === null) {
      sheet.style.removeProperty('--keyboard-lift');
      sheet.style.removeProperty('--visible-height');
    } else {
      sheet.style.setProperty('--keyboard-lift', `${String(lift.lift)}px`);
      sheet.style.setProperty('--visible-height', `${String(lift.height)}px`);
    }
    // After the new size lays out.
    frame = requestAnimationFrame(showFocused);
  };

  const onFocus = (): void => {
    frame = requestAnimationFrame(update);
  };

  viewport.addEventListener('resize', update);
  viewport.addEventListener('scroll', update);
  sheet.addEventListener('focusin', onFocus);
  update();
  return () => {
    cancelAnimationFrame(frame);
    viewport.removeEventListener('resize', update);
    viewport.removeEventListener('scroll', update);
    sheet.removeEventListener('focusin', onFocus);
  };
}
