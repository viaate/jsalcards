/** Where a page's parts sit against its screen, read in the page (page.evaluate). */

/** The screen's sides a part must keep clear of: its safe areas. */
export interface Clear {
  /** The selectors to read, each to match at least one part, and whether its words are checked. */
  parts: [string, boolean][];
  left: number;
  right: number;
}

/**
 * Every part of `parts` off the screen across, or not clear of its safe areas, or with its
 * words cut off at either end; and the page wider than the screen or scrolling sideways. `boxes`
 * is where everything sits, to tell when the page has settled after a resize.
 */
export function offScreen({ parts, left, right }: Clear): {
  problems: string[];
  boxes: string;
} {
  const problems: string[] = [];
  const boxes: string[] = [];
  const width = window.innerWidth;
  const height = window.innerHeight;
  const root = document.documentElement;
  if (root.scrollWidth > root.clientWidth) {
    problems.push(`page ${String(root.scrollWidth)} wide in ${String(root.clientWidth)}`);
  }
  window.scrollTo(10_000, 0);
  if (window.scrollX !== 0) problems.push(`page scrolls ${String(window.scrollX)} sideways`);
  window.scrollTo(0, 0);
  for (const [selector, words] of parts) {
    const nodes = [...document.querySelectorAll(selector)];
    if (nodes.length === 0) problems.push(`${selector} missing`);
    for (const node of nodes) {
      const box = node.getBoundingClientRect();
      boxes.push(
        `${selector} ${box.left.toFixed(1)} ${box.top.toFixed(1)} ${box.width.toFixed(1)}`,
      );
      if (box.width === 0) continue;
      const where = `${selector} ${box.left.toFixed(1)}–${box.right.toFixed(1)} × ${box.top.toFixed(1)}–${box.bottom.toFixed(1)}`;
      if (box.left < left - 0.5 || box.right > width - right + 0.5) {
        problems.push(`${where} across`);
      }
      if (box.top < -0.5 || box.bottom > height + 0.5) problems.push(`${where} down`);
      if (words && node.scrollWidth > node.clientWidth + 1 && node.clientWidth > 0) {
        problems.push(`${where} words ${String(node.scrollWidth)} in ${String(node.clientWidth)}`);
      }
    }
  }
  return { problems, boxes: boxes.join('\n') };
}
