/**
 * The view a cut leaves, held on screen until the map has drawn the place it
 * cut to.
 *
 * A search pick far from the streets on screen does not fly there over
 * streets the map has none of (index.ts): it cuts to its stop over the
 * destination and glides in from there. Before the cut, the frame the map is
 * showing is copied onto a canvas over the map, still; once the map has
 * drawn the new place, the copy fades out over it. The viewer sees the view
 * they left, then the new one, never the black of a map still loading.
 *
 * The copy is taken while MapLibre's frame is drawn (its "render" event): a
 * WebGL canvas that keeps no drawing buffer is empty once the frame is on
 * screen. It is a plain canvas with an opacity, no filter or blend over the
 * map, and it takes no pointer events.
 */

/** How long the held frame takes to fade out over the new place, in milliseconds. */
export const HELD_FRAME_FADE_MS = 300;

/** Class on the held frame, for tests and styles. */
export const HELD_FRAME_CLASS = 'held-frame';

export interface HeldFrame {
  /**
   * Copies what `source` shows now onto the held frame, over it; false, and
   * nothing is held, where the page cannot copy it.
   */
  hold(source: HTMLCanvasElement): boolean;
  /** Lets the held frame go: fading out over the map, or at once. */
  release(fade: boolean): void;
  /** Whether a frame is held, fading or not. */
  readonly held: boolean;
}

/** A held frame for a map: drawn right over the canvas it copies. */
export function heldFrame(): HeldFrame {
  let canvas: HTMLCanvasElement | null = null;
  let timer: number | undefined;
  const remove = (): void => {
    window.clearTimeout(timer);
    timer = undefined;
    canvas?.remove();
    canvas = null;
  };
  return {
    hold(source) {
      remove();
      const copy = document.createElement('canvas');
      copy.className = HELD_FRAME_CLASS;
      copy.width = source.width;
      copy.height = source.height;
      copy.setAttribute('aria-hidden', 'true');
      const context = copy.getContext('2d');
      if (context === null) return false;
      try {
        context.drawImage(source, 0, 0);
      } catch {
        return false;
      }
      Object.assign(copy.style, {
        position: 'absolute',
        left: '0',
        top: '0',
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        opacity: '1',
      });
      source.after(copy);
      canvas = copy;
      return true;
    },
    release(fade) {
      const copy = canvas;
      if (copy === null) return;
      if (!fade) {
        remove();
        return;
      }
      if (timer !== undefined) return;
      copy.style.transition = `opacity ${String(HELD_FRAME_FADE_MS)}ms ease-out`;
      // Starts from the opacity it is drawn at: the change goes in the next frame.
      requestAnimationFrame(() => {
        copy.style.opacity = '0';
      });
      timer = window.setTimeout(remove, HELD_FRAME_FADE_MS + 50);
    },
    get held() {
      return canvas !== null;
    },
  };
}
